"""Hybrid search & ingestion — merged from RAG service.

Provides:
  - Hybrid search: alpha * vector_score + (1-alpha) * bm25_score
  - Document ingestion: chunk → embed → store in Qdrant + Meilisearch
  - Collection management
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File

from local_system.config import get_settings
from local_system.models import (
    Document,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from local_system.utils import generate_id, setup_logging

settings = get_settings()
logger = setup_logging("memory.search", settings)

router = APIRouter(tags=["search"])


# --- Module-level references (set by memory main.py at startup) ---

_qdrant = None
_meili = None
_http_client = None


def init(qdrant, meili, http_client):
    """Called by memory main.py after backends are ready."""
    global _qdrant, _meili, _http_client
    _qdrant = qdrant
    _meili = meili
    _http_client = http_client


def _embedding_url() -> str:
    return settings.inference.vllm_embedding_host


# --- Collections ---


@router.get("/v1/collections")
async def list_collections() -> list[dict]:
    """List all document collections."""
    if not _qdrant:
        raise HTTPException(status_code=503, detail="Qdrant not available")
    collections = await _qdrant.get_collections()
    result = []
    for c in collections.collections:
        info = await _qdrant.get_collection(c.name)
        result.append({
            "name": c.name,
            "vectors_count": info.vectors_count,
            "points_count": info.points_count,
        })
    return result


@router.post("/v1/collections/{name}")
async def create_collection(name: str, dimensions: int | None = None) -> dict:
    """Create a new document collection in both Qdrant and Meilisearch."""
    if not _qdrant:
        raise HTTPException(status_code=503, detail="Qdrant not available")
    from qdrant_client.models import Distance, VectorParams

    dims = dimensions or settings.rag.embedding_dimensions
    await _qdrant.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=dims, distance=Distance.COSINE),
    )
    if _meili:
        try:
            _meili.create_index(name, {"primaryKey": "id"})
        except Exception as e:
            logger.warning(f"Meilisearch index creation failed: {e}")
    return {"name": name, "dimensions": dims, "status": "created"}


# --- Ingestion ---


@router.post("/v1/ingest")
async def ingest(
    collection: str = "default",
    texts: list[str] | None = None,
    sources: list[str] | None = None,
) -> dict:
    """Ingest text documents — chunks, embeds, stores in Qdrant + Meilisearch."""
    if not _qdrant:
        raise HTTPException(status_code=503, detail="Qdrant not available")

    try:
        await _qdrant.get_collection(collection)
    except Exception:
        await create_collection(collection)

    if not texts:
        return {"documents_processed": 0, "chunks_created": 0}

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

    chunk_texts = [c["content"] for c in all_chunks]
    embeddings = await _get_embeddings(chunk_texts)

    from qdrant_client.models import PointStruct

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
    await _qdrant.upsert(collection_name=collection, points=points)

    if _meili:
        try:
            index = _meili.index(collection)
            meili_docs = [
                {"id": c["id"], "source": c["source"], "content": c["content"], "chunk_index": c["chunk_index"]}
                for c in all_chunks
            ]
            index.add_documents(meili_docs)
        except Exception as e:
            logger.warning(f"Meilisearch indexing failed: {e}")

    return {"documents_processed": len(texts), "chunks_created": len(all_chunks)}


@router.post("/v1/ingest/file")
async def ingest_file(
    file: UploadFile = File(...),
    collection: str = "default",
) -> dict:
    """Ingest a file (plain text, markdown, etc.)."""
    content = (await file.read()).decode("utf-8", errors="replace")
    return await ingest(collection=collection, texts=[content], sources=[file.filename or "uploaded_file"])


# --- Hybrid Search ---


@router.post("/v1/search", response_model=SearchResponse)
async def search(body: SearchRequest) -> SearchResponse:
    """Hybrid search: alpha * vector_score + (1-alpha) * bm25_score."""
    if not _qdrant:
        raise HTTPException(status_code=503, detail="Qdrant not available")

    alpha = body.alpha if body.use_hybrid else 1.0
    vector_results: list[SearchResult] = []
    bm25_results: list[SearchResult] = []

    query_embeddings = await _get_embeddings([body.query])
    if query_embeddings:
        hits_resp = await _qdrant.query_points(
            collection_name=body.collection,
            query=query_embeddings[0],
            limit=body.top_k * 2,
            score_threshold=body.score_threshold or None,
        )
        for hit in hits_resp.points:
            payload = hit.payload or {}
            vector_results.append(
                SearchResult(
                    document=Document(
                        id=payload.get("doc_id", "") or payload.get("source_id", ""),
                        source=payload.get("source", ""),
                        content=payload.get("content", "") or payload.get("text", ""),
                        chunk_index=payload.get("chunk_index", 0),
                    ),
                    score=hit.score,
                    source="vector",
                )
            )

    if body.use_hybrid and _meili:
        try:
            index = _meili.index(body.collection)
            meili_hits = index.search(body.query, {"limit": body.top_k * 2})
            max_score = len(meili_hits.get("hits", []))
            for i, hit in enumerate(meili_hits.get("hits", [])):
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


async def _get_embeddings(texts: list[str]) -> list[list[float]]:
    """Get embeddings from vLLM (Qwen3-Embedding-0.6B) via OpenAI-compatible API."""
    if not _http_client:
        logger.error("HTTP client not initialized")
        return []
    try:
        resp = await _http_client.post(
            f"{_embedding_url()}/v1/embeddings",
            json={"model": settings.rag.embedding_model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data.get("data", [])]
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        return []


def _merge_hybrid_results(
    vector_results: list[SearchResult],
    bm25_results: list[SearchResult],
    alpha: float,
    top_k: int,
) -> list[SearchResult]:
    """Merge vector and BM25 results with alpha weighting."""
    scores: dict[str, dict] = {}

    for r in vector_results:
        doc_id = r.document.id
        scores[doc_id] = {"result": r, "vector_score": r.score, "bm25_score": 0.0}

    for r in bm25_results:
        doc_id = r.document.id
        if doc_id in scores:
            scores[doc_id]["bm25_score"] = r.score
        else:
            scores[doc_id] = {"result": r, "vector_score": 0.0, "bm25_score": r.score}

    merged = []
    for doc_id, data in scores.items():
        combined = alpha * data["vector_score"] + (1 - alpha) * data["bm25_score"]
        result = data["result"]
        result.score = combined
        result.source = "hybrid"
        merged.append(result)

    merged.sort(key=lambda x: x.score, reverse=True)
    return merged[:top_k]
