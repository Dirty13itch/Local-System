"""RAG Service — hybrid search with Qdrant vectors + Meilisearch BM25.

Proven architecture from Hydra:
  - Qdrant: 768-dim vectors from nomic-embed-text for semantic search
  - Meilisearch: BM25 full-text search for keyword matching
  - Hybrid: alpha-weighted combination (default 0.7 vector, 0.3 BM25)

Runs on hydra-storage alongside the databases.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

from local_system.config import get_settings
from local_system.models import (
    Document,
    HealthResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from local_system.utils import generate_id, setup_logging

settings = get_settings()
logger = setup_logging("rag", settings)

_meili = None  # Meilisearch client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _meili
    logger.info("RAG service starting")
    app.state.qdrant = AsyncQdrantClient(
        host=settings.qdrant.host,
        port=settings.qdrant.port,
    )
    app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
    app.state.start_time = time.time()

    # Initialize Meilisearch for BM25 search
    try:
        import meilisearch

        _meili = meilisearch.Client(
            settings.meilisearch.url,
            settings.meilisearch.key,
        )
        _meili.health()
        logger.info("Meilisearch connected for BM25 search")
    except Exception as e:
        logger.warning(f"Meilisearch not available: {e}")
        _meili = None

    yield
    await app.state.qdrant.close()
    await app.state.http_client.aclose()
    logger.info("RAG service stopped")


app = FastAPI(
    title="Athanor RAG",
    version="0.1.0",
    lifespan=lifespan,
)


def _embedding_url() -> str:
    """Ollama GPU endpoint for embeddings."""
    return settings.inference.ollama_gpu_host


@app.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(
        service="rag",
        node=settings.node.name.value,
        uptime_seconds=time.time() - app.state.start_time,
    )


# --- Collections ---


@app.get("/v1/collections")
async def list_collections() -> list[dict]:
    """List all document collections."""
    qdrant: AsyncQdrantClient = app.state.qdrant
    collections = await qdrant.get_collections()
    result = []
    for c in collections.collections:
        info = await qdrant.get_collection(c.name)
        result.append({
            "name": c.name,
            "vectors_count": info.vectors_count,
            "points_count": info.points_count,
        })
    return result


@app.post("/v1/collections/{name}")
async def create_collection(name: str, dimensions: int | None = None) -> dict:
    """Create a new document collection in both Qdrant and Meilisearch."""
    qdrant: AsyncQdrantClient = app.state.qdrant
    dims = dimensions or settings.rag.embedding_dimensions

    # Create Qdrant collection
    await qdrant.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=dims, distance=Distance.COSINE),
    )

    # Create Meilisearch index
    if _meili:
        try:
            _meili.create_index(name, {"primaryKey": "id"})
        except Exception as e:
            logger.warning(f"Meilisearch index creation failed: {e}")

    return {"name": name, "dimensions": dims, "status": "created"}


# --- Ingestion ---


@app.post("/v1/ingest")
async def ingest(
    collection: str = "default",
    texts: list[str] | None = None,
    sources: list[str] | None = None,
) -> dict:
    """Ingest text documents — chunks, embeds, stores in Qdrant + Meilisearch."""
    qdrant: AsyncQdrantClient = app.state.qdrant
    client: httpx.AsyncClient = app.state.http_client

    # Ensure collection exists
    try:
        await qdrant.get_collection(collection)
    except Exception:
        await create_collection(collection)

    if not texts:
        return {"documents_processed": 0, "chunks_created": 0}

    # Chunk all texts
    all_chunks: list[dict] = []
    for i, text in enumerate(texts):
        source = sources[i] if sources and i < len(sources) else f"doc_{i}"
        chunks = _chunk_text(text, settings.rag.chunk_size, settings.rag.chunk_overlap)
        for j, chunk in enumerate(chunks):
            chunk_id = generate_id("chunk")
            all_chunks.append({
                "id": chunk_id,
                "source": source,
                "content": chunk,
                "chunk_index": j,
            })

    # Generate embeddings via Ollama GPU
    chunk_texts = [c["content"] for c in all_chunks]
    embeddings = await _get_embeddings(client, chunk_texts)

    # Store in Qdrant (vector search)
    points = []
    for chunk, embedding in zip(all_chunks, embeddings):
        points.append(
            PointStruct(
                id=abs(hash(chunk["id"])) % (2**63),
                vector=embedding,
                payload={
                    "doc_id": chunk["id"],
                    "source": chunk["source"],
                    "content": chunk["content"],
                    "chunk_index": chunk["chunk_index"],
                },
            )
        )
    await qdrant.upsert(collection_name=collection, points=points)

    # Store in Meilisearch (BM25 search)
    if _meili:
        try:
            index = _meili.index(collection)
            meili_docs = [
                {
                    "id": c["id"],
                    "source": c["source"],
                    "content": c["content"],
                    "chunk_index": c["chunk_index"],
                }
                for c in all_chunks
            ]
            index.add_documents(meili_docs)
        except Exception as e:
            logger.warning(f"Meilisearch indexing failed: {e}")

    return {
        "documents_processed": len(texts),
        "chunks_created": len(all_chunks),
    }


@app.post("/v1/ingest/file")
async def ingest_file(
    file: UploadFile = File(...),
    collection: str = "default",
) -> dict:
    """Ingest a file (plain text, markdown, etc.)."""
    content = (await file.read()).decode("utf-8", errors="replace")
    return await ingest(
        collection=collection,
        texts=[content],
        sources=[file.filename or "uploaded_file"],
    )


# --- Hybrid Search ---


@app.post("/v1/search", response_model=SearchResponse)
async def search(body: SearchRequest) -> SearchResponse:
    """Hybrid search: alpha * vector_score + (1-alpha) * bm25_score."""
    qdrant: AsyncQdrantClient = app.state.qdrant
    client: httpx.AsyncClient = app.state.http_client

    alpha = body.alpha if body.use_hybrid else 1.0
    vector_results: list[SearchResult] = []
    bm25_results: list[SearchResult] = []

    # Vector search (Qdrant)
    query_embeddings = await _get_embeddings(client, [body.query])
    if query_embeddings:
        hits = await qdrant.search(
            collection_name=body.collection,
            query_vector=query_embeddings[0],
            limit=body.top_k * 2,  # Over-fetch for hybrid merging
            score_threshold=body.score_threshold or None,
        )
        for hit in hits:
            payload = hit.payload or {}
            vector_results.append(
                SearchResult(
                    document=Document(
                        id=payload.get("doc_id", ""),
                        source=payload.get("source", ""),
                        content=payload.get("content", ""),
                        chunk_index=payload.get("chunk_index", 0),
                    ),
                    score=hit.score,
                    source="vector",
                )
            )

    # BM25 search (Meilisearch)
    if body.use_hybrid and _meili:
        try:
            index = _meili.index(body.collection)
            meili_hits = index.search(body.query, {"limit": body.top_k * 2})
            max_score = len(meili_hits.get("hits", []))
            for i, hit in enumerate(meili_hits.get("hits", [])):
                # Normalize BM25 rank to 0-1 score
                normalized_score = (max_score - i) / max_score if max_score > 0 else 0
                bm25_results.append(
                    SearchResult(
                        document=Document(
                            id=hit.get("id", ""),
                            source=hit.get("source", ""),
                            content=hit.get("content", ""),
                            chunk_index=hit.get("chunk_index", 0),
                        ),
                        score=normalized_score,
                        source="bm25",
                    )
                )
        except Exception as e:
            logger.warning(f"Meilisearch search failed: {e}")

    # Merge results with alpha weighting
    if body.use_hybrid and bm25_results:
        results = _merge_hybrid_results(vector_results, bm25_results, alpha, body.top_k)
    else:
        results = vector_results[: body.top_k]

    return SearchResponse(results=results, query=body.query, total=len(results))


# --- Helpers ---


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


async def _get_embeddings(client: httpx.AsyncClient, texts: list[str]) -> list[list[float]]:
    """Get embeddings from Ollama GPU (nomic-embed-text)."""
    try:
        resp = await client.post(
            f"{_embedding_url()}/api/embed",
            json={"model": settings.rag.embedding_model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("embeddings", [])
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        return []


def _merge_hybrid_results(
    vector_results: list[SearchResult],
    bm25_results: list[SearchResult],
    alpha: float,
    top_k: int,
) -> list[SearchResult]:
    """Merge vector and BM25 results with alpha weighting.

    Combined score = alpha * vector_score + (1 - alpha) * bm25_score
    """
    # Build lookup by document ID
    scores: dict[str, dict] = {}

    for r in vector_results:
        doc_id = r.document.id
        scores[doc_id] = {
            "result": r,
            "vector_score": r.score,
            "bm25_score": 0.0,
        }

    for r in bm25_results:
        doc_id = r.document.id
        if doc_id in scores:
            scores[doc_id]["bm25_score"] = r.score
        else:
            scores[doc_id] = {
                "result": r,
                "vector_score": 0.0,
                "bm25_score": r.score,
            }

    # Calculate combined scores
    merged = []
    for doc_id, data in scores.items():
        combined = alpha * data["vector_score"] + (1 - alpha) * data["bm25_score"]
        result = data["result"]
        result.score = combined
        result.source = "hybrid"
        merged.append(result)

    merged.sort(key=lambda x: x.score, reverse=True)
    return merged[:top_k]
