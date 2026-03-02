"""RAG Service — document ingestion, embedding, and retrieval.

Handles document chunking, embedding generation (via inference service),
vector storage (Qdrant), and semantic search. Runs on VAULT.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter

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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("RAG service starting")
    app.state.qdrant = AsyncQdrantClient(
        host=settings.qdrant.host,
        port=settings.qdrant.port,
    )
    app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
    app.state.start_time = time.time()
    yield
    await app.state.qdrant.close()
    await app.state.http_client.aclose()
    logger.info("RAG service stopped")


app = FastAPI(
    title="Local-System RAG",
    version="0.1.0",
    lifespan=lifespan,
)


def _inference_url() -> str:
    return f"http://{settings.network.node1_host}:{settings.ports.inference}"


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
    """Create a new document collection."""
    qdrant: AsyncQdrantClient = app.state.qdrant
    dims = dimensions or settings.rag.embedding_dimensions
    await qdrant.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=dims, distance=Distance.COSINE),
    )
    return {"name": name, "dimensions": dims, "status": "created"}


# --- Ingestion ---


@app.post("/v1/ingest")
async def ingest(
    collection: str = "default",
    texts: list[str] | None = None,
    sources: list[str] | None = None,
) -> dict:
    """Ingest text documents into a collection.

    Chunks the input, generates embeddings, and stores in Qdrant.
    """
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
            all_chunks.append({
                "id": generate_id("chunk"),
                "source": source,
                "content": chunk,
                "chunk_index": j,
            })

    # Generate embeddings in batch
    chunk_texts = [c["content"] for c in all_chunks]
    embeddings = await _get_embeddings(client, chunk_texts)

    # Store in Qdrant
    points = []
    doc_ids = []
    for chunk, embedding in zip(all_chunks, embeddings):
        point_id = chunk["id"]
        doc_ids.append(point_id)
        points.append(
            PointStruct(
                id=hash(point_id) % (2**63),
                vector=embedding,
                payload={
                    "doc_id": point_id,
                    "source": chunk["source"],
                    "content": chunk["content"],
                    "chunk_index": chunk["chunk_index"],
                },
            )
        )

    await qdrant.upsert(collection_name=collection, points=points)

    return {
        "documents_processed": len(texts),
        "chunks_created": len(all_chunks),
        "document_ids": doc_ids,
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


# --- Search ---


@app.post("/v1/search", response_model=SearchResponse)
async def search(body: SearchRequest) -> SearchResponse:
    """Semantic search across a document collection."""
    qdrant: AsyncQdrantClient = app.state.qdrant
    client: httpx.AsyncClient = app.state.http_client

    # Embed the query
    query_embeddings = await _get_embeddings(client, [body.query])
    if not query_embeddings:
        raise HTTPException(status_code=500, detail="Failed to generate query embedding")

    # Search Qdrant
    hits = await qdrant.search(
        collection_name=body.collection,
        query_vector=query_embeddings[0],
        limit=body.top_k,
        score_threshold=body.score_threshold or None,
    )

    results = []
    for hit in hits:
        payload = hit.payload or {}
        results.append(
            SearchResult(
                document=Document(
                    id=payload.get("doc_id", ""),
                    source=payload.get("source", ""),
                    content=payload.get("content", ""),
                    chunk_index=payload.get("chunk_index", 0),
                ),
                score=hit.score,
            )
        )

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
    """Get embeddings from the inference service."""
    try:
        resp = await client.post(
            f"{_inference_url()}/v1/embeddings",
            json={"model": settings.rag.embedding_model, "texts": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("embeddings", [])
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        return []
