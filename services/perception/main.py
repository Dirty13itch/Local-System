"""Perception Service — ingest, chunk, embed, index.

Ingests content from files, text, and URLs into the memory system.
Handles: chunking -> embedding -> indexing into Qdrant + Meilisearch.

Runs on DEV (:8730). Feeds the Memory service's resource tier.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field

from local_system.config import get_settings
from local_system.utils import generate_id, setup_logging

from .chunkers import (
    Chunk,
    chunk_content,
    detect_content_type,
    detect_language,
)
from .watchers import DirectoryWatcher, WatchConfig, FileChange

settings = get_settings()
logger = setup_logging("perception", settings)

# --- Clients (initialized in lifespan) ---
_http: httpx.AsyncClient | None = None
_qdrant = None
_meili = None
_watchers: list[DirectoryWatcher] = []
_watcher_tasks: list[asyncio.Task] = []


# --- Models ---

class IngestTextRequest(BaseModel):
    """Ingest raw text content."""
    content: str
    source: str = "manual"
    content_type: str = "text"  # text, markdown, code
    language: str = "python"    # For code content_type
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class IngestURLRequest(BaseModel):
    """Ingest content from a URL."""
    url: str
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class IngestResponse(BaseModel):
    """Response from an ingest operation."""
    source_id: str
    chunks_created: int
    chunks_indexed: int
    content_type: str
    source: str


class IngestStats(BaseModel):
    """Current ingestion statistics."""
    total_ingested: int = 0
    total_chunks: int = 0
    total_errors: int = 0
    watched_directories: int = 0
    uptime_seconds: float = 0


# --- Globals ---
_stats = {"ingested": 0, "chunks": 0, "errors": 0}


# --- Embedding helper ---

async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Get embeddings for a batch of texts via vLLM."""
    if not _http:
        raise RuntimeError("HTTP client not initialized")

    resp = await _http.post(
        f"{settings.inference.vllm_embedding_host}/v1/embeddings",
        json={"model": settings.rag.embedding_model, "input": texts},
        timeout=60.0,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    # Sort by index to maintain order
    data.sort(key=lambda x: x["index"])
    return [d["embedding"] for d in data]


# --- Core ingest pipeline ---

async def ingest_chunks(
    chunks: list[Chunk],
    source: str,
    source_id: str,
    tags: list[str] | None = None,
) -> int:
    """Embed and index a list of chunks into Qdrant + Meilisearch.

    Returns the number of chunks successfully indexed.
    """
    if not chunks:
        return 0

    tags = tags or []
    indexed = 0

    # Batch embed (up to 32 at a time for vLLM)
    batch_size = 32
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        texts = [c.text for c in batch]

        try:
            embeddings = await get_embeddings(texts)
        except Exception as e:
            logger.error(f"Embedding failed for batch {i}: {e}")
            _stats["errors"] += 1
            continue

        # Index into Qdrant
        if _qdrant:
            try:
                from qdrant_client.models import PointStruct
                points = []
                for j, (chunk, embedding) in enumerate(zip(batch, embeddings)):
                    points.append(PointStruct(
                        id=str(__import__("uuid").uuid5(__import__("uuid").NAMESPACE_URL, f"{source_id}:{chunk.index}:{j}")),
                        vector=embedding,
                        payload={
                            "text": chunk.text,
                            "source": source,
                            "source_id": source_id,
                            "chunk_index": chunk.index,
                            "tags": tags,
                            "content_type": chunk.metadata.get("chunk_type", "text"),
                            **chunk.metadata,
                        },
                    ))

                await _qdrant.upsert(
                    collection_name="resources",
                    points=points,
                )
                indexed += len(points)
            except Exception as e:
                logger.error(f"Qdrant indexing failed: {e}")
                _stats["errors"] += 1

        # Index into Meilisearch for BM25
        if _meili:
            try:
                docs = []
                for j, chunk in enumerate(batch):
                    doc_id = hashlib.md5(
                        f"{source_id}:{chunk.index}:{j}".encode()
                    ).hexdigest()[:24]
                    docs.append({
                        "id": doc_id,
                        "text": chunk.text,
                        "source": source,
                        "source_id": source_id,
                        "chunk_index": chunk.index,
                        "tags": tags,
                        "content_type": chunk.metadata.get("chunk_type", "text"),
                    })
                await _http.post(
                    f"{settings.meilisearch.url}/indexes/resources/documents",
                    json=docs,
                    headers={"Authorization": f"Bearer {settings.meilisearch.key}"},
                    timeout=30.0,
                )
            except Exception as e:
                logger.error(f"Meilisearch indexing failed: {e}")

    return indexed


# --- File change handler (for watchers) ---

async def handle_file_changes(changes: list[FileChange]) -> None:
    """Process file changes detected by watchers."""
    for change in changes:
        try:
            # Skip very large files (>10MB)
            if change.size > 10 * 1024 * 1024:
                logger.warning(f"Skipping large file ({change.size} bytes): {change.path}")
                continue

            with open(change.path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            content_type = detect_content_type(change.path)
            language = detect_language(change.path)
            source_id = generate_id("watch")

            chunks = chunk_content(
                content,
                content_type=content_type,
                language=language,
                metadata={"file_path": change.path, "event_type": change.event_type},
            )

            indexed = await ingest_chunks(
                chunks,
                source=change.path,
                source_id=source_id,
                tags=["auto-ingested", f"event:{change.event_type}"],
            )

            _stats["ingested"] += 1
            _stats["chunks"] += indexed
            logger.info(f"Auto-ingested {change.path}: {indexed} chunks")

        except Exception as e:
            logger.error(f"Failed to ingest {change.path}: {e}")
            _stats["errors"] += 1


# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _http, _qdrant, _meili

    logger.info("Perception service starting")
    app.state.start_time = time.time()

    # HTTP client
    _http = httpx.AsyncClient(timeout=httpx.Timeout(60.0))

    # Qdrant
    try:
        from qdrant_client import AsyncQdrantClient
        from qdrant_client.models import VectorParams, Distance
        _qdrant = AsyncQdrantClient(
            host=settings.qdrant.host,
            port=settings.qdrant.port,
        )
        # Ensure resources collection exists
        collections = await _qdrant.get_collections()
        names = [c.name for c in collections.collections]
        if "resources" not in names:
            await _qdrant.create_collection(
                collection_name="resources",
                vectors_config=VectorParams(
                    size=settings.rag.embedding_dimensions,
                    distance=Distance.COSINE,
                ),
            )
            logger.info("Created Qdrant 'resources' collection")
        logger.info("Qdrant connected")
    except Exception as e:
        logger.warning(f"Qdrant not available: {e}")
        _qdrant = None

    # Meilisearch
    try:
        resp = await _http.get(
            f"{settings.meilisearch.url}/health",
            headers={"Authorization": f"Bearer {settings.meilisearch.key}"},
        )
        if resp.status_code == 200:
            # Ensure resources index exists
            try:
                await _http.post(
                    f"{settings.meilisearch.url}/indexes",
                    json={"uid": "resources", "primaryKey": "id"},
                    headers={"Authorization": f"Bearer {settings.meilisearch.key}"},
                )
            except Exception:
                pass  # Index may already exist
            _meili = True
            logger.info("Meilisearch connected")
        else:
            _meili = None
            logger.warning(f"Meilisearch unhealthy: {resp.status_code}")
    except Exception as e:
        logger.warning(f"Meilisearch not available: {e}")
        _meili = None

    # Start file watchers (configured directories)
    watch_configs = [
        WatchConfig(
            path="/mnt/vault/data/documents",
            patterns=["*.md", "*.txt", "*.pdf"],
            poll_interval=60.0,
        ),
        WatchConfig(
            path="/home/shaun/dev/local-system-v4/docs",
            patterns=["*.md"],
            poll_interval=120.0,
        ),
    ]

    for wc in watch_configs:
        watcher = DirectoryWatcher(wc)
        _watchers.append(watcher)
        task = asyncio.create_task(watcher.watch(handle_file_changes))
        _watcher_tasks.append(task)

    logger.info(f"Started {len(_watchers)} file watchers")

    yield

    # Shutdown
    logger.info("Perception service shutting down")
    for w in _watchers:
        w.stop()
    for t in _watcher_tasks:
        t.cancel()
    if _http:
        await _http.aclose()
    if _qdrant:
        await _qdrant.close()


# --- FastAPI app ---

app = FastAPI(
    title="Perception Service",
    description="Ingest, chunk, embed, index — the sensory pipeline",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Health check."""
    return {
        "status": "healthy",
        "service": "perception",
        "qdrant": _qdrant is not None,
        "meilisearch": _meili is not None,
        "watchers": len(_watchers),
        "uptime": time.time() - app.state.start_time,
    }


@app.get("/stats", response_model=IngestStats)
async def get_stats():
    """Get ingestion statistics."""
    return IngestStats(
        total_ingested=_stats["ingested"],
        total_chunks=_stats["chunks"],
        total_errors=_stats["errors"],
        watched_directories=len(_watchers),
        uptime_seconds=time.time() - app.state.start_time,
    )


@app.post("/ingest/text", response_model=IngestResponse)
async def ingest_text(req: IngestTextRequest):
    """Ingest raw text content — chunk, embed, index."""
    source_id = generate_id("ingest")

    chunks = chunk_content(
        req.content,
        content_type=req.content_type,
        language=req.language,
        metadata=req.metadata,
    )

    if not chunks:
        raise HTTPException(status_code=400, detail="No chunks produced from content")

    indexed = await ingest_chunks(
        chunks,
        source=req.source,
        source_id=source_id,
        tags=req.tags,
    )

    _stats["ingested"] += 1
    _stats["chunks"] += indexed

    return IngestResponse(
        source_id=source_id,
        chunks_created=len(chunks),
        chunks_indexed=indexed,
        content_type=req.content_type,
        source=req.source,
    )


@app.post("/ingest/file", response_model=IngestResponse)
async def ingest_file(
    file: UploadFile = File(...),
    tags: str = Form(""),
):
    """Ingest an uploaded file — detect type, chunk, embed, index."""
    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 text")

    content_type = detect_content_type(file.filename or "unknown.txt")
    language = detect_language(file.filename or "unknown.txt")
    source_id = generate_id("file")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    chunks = chunk_content(
        text,
        content_type=content_type,
        language=language,
        metadata={"filename": file.filename},
    )

    if not chunks:
        raise HTTPException(status_code=400, detail="No chunks produced from file")

    indexed = await ingest_chunks(
        chunks,
        source=file.filename or "upload",
        source_id=source_id,
        tags=tag_list,
    )

    _stats["ingested"] += 1
    _stats["chunks"] += indexed

    return IngestResponse(
        source_id=source_id,
        chunks_created=len(chunks),
        chunks_indexed=indexed,
        content_type=content_type,
        source=file.filename or "upload",
    )


@app.post("/ingest/url", response_model=IngestResponse)
async def ingest_url(req: IngestURLRequest):
    """Ingest content from a URL — fetch, chunk, embed, index."""
    if not _http:
        raise HTTPException(status_code=503, detail="HTTP client not ready")

    try:
        resp = await _http.get(req.url, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
        text = resp.text
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch URL: {e}")

    # Detect type from URL or content-type header
    ct = resp.headers.get("content-type", "")
    if "markdown" in ct or req.url.endswith(".md"):
        content_type = "markdown"
    elif "html" in ct:
        # Basic HTML stripping (for now, just extract text)
        import re
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        content_type = "text"
    else:
        content_type = "text"

    source_id = generate_id("url")

    chunks = chunk_content(
        text,
        content_type=content_type,
        metadata={"url": req.url, **req.metadata},
    )

    if not chunks:
        raise HTTPException(status_code=400, detail="No chunks produced from URL content")

    indexed = await ingest_chunks(
        chunks,
        source=req.url,
        source_id=source_id,
        tags=req.tags,
    )

    _stats["ingested"] += 1
    _stats["chunks"] += indexed

    return IngestResponse(
        source_id=source_id,
        chunks_created=len(chunks),
        chunks_indexed=indexed,
        content_type=content_type,
        source=req.url,
    )


@app.post("/ingest/batch", response_model=list[IngestResponse])
async def ingest_batch(items: list[IngestTextRequest]):
    """Ingest multiple text items in one request."""
    results = []
    for item in items:
        source_id = generate_id("batch")
        chunks = chunk_content(
            item.content,
            content_type=item.content_type,
            language=item.language,
            metadata=item.metadata,
        )
        indexed = await ingest_chunks(
            chunks,
            source=item.source,
            source_id=source_id,
            tags=item.tags,
        )
        _stats["ingested"] += 1
        _stats["chunks"] += indexed
        results.append(IngestResponse(
            source_id=source_id,
            chunks_created=len(chunks),
            chunks_indexed=indexed,
            content_type=item.content_type,
            source=item.source,
        ))
    return results


@app.get("/watchers")
async def list_watchers():
    """List active file watchers."""
    return [
        {
            "path": w.config.path,
            "patterns": w.config.patterns,
            "recursive": w.config.recursive,
            "poll_interval": w.config.poll_interval,
            "known_files": len(w._known_files),
        }
        for w in _watchers
    ]


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus metrics endpoint."""
    from local_system.metrics import metrics_response, SERVICE_INFO
    SERVICE_INFO.labels(service="perception", version="0.1.0", node=settings.node.name.value).set(1)
    return metrics_response()
