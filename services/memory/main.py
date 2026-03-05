"""Memory Service — 6-tier cognitive memory system + hybrid search.

Implements the memory architecture inspired by human cognition:
  1. Procedural — How to do things (versioned files)
  2. Working — Active context, current task state (Redis)
  3. Episodic — What happened when (Qdrant + timestamps)
  4. Semantic — Knowledge graph entities and relationships (Neo4j/Graphiti)
  5. Resource — Ingested documents, code, papers (Qdrant chunks)
  6. Knowledge Vault — Validated high-confidence facts (PostgreSQL + Qdrant)

Also provides hybrid search (Qdrant vector + Meilisearch BM25) and document
ingestion — merged from the former RAG service.

Runs on VAULT. Memory consolidation happens during idle periods.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException

from local_system.config import get_settings
from local_system.models import (
    EpisodicEvent,
    HealthResponse,
    MemoryEntry,
    MemorySearchRequest,
    MemorySearchResponse,
    MemoryTier,
    WorkingContext,
)
from local_system.utils import generate_id, setup_logging

from . import search as search_module

settings = get_settings()
logger = setup_logging("memory", settings)


# --- Storage backends (initialized at startup) ---

_redis = None     # Working memory
_qdrant = None    # Episodic + Resource memory
_neo4j = None     # Semantic memory
_pg = None        # Knowledge Vault
_meili = None     # BM25 full-text search


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _redis, _qdrant, _meili
    logger.info("Memory service starting")
    app.state.start_time = time.time()

    # HTTP client for embedding requests
    app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))

    # Initialize Redis for working memory
    try:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(settings.redis.url, decode_responses=True)
        await _redis.ping()
        logger.info("Redis connected for working memory")
    except Exception as e:
        logger.warning(f"Redis not available: {e}")

    # Initialize Qdrant for episodic + resource memory + vector search
    try:
        from qdrant_client import AsyncQdrantClient

        _qdrant = AsyncQdrantClient(
            host=settings.qdrant.host,
            port=settings.qdrant.port,
        )
        collections = await _qdrant.get_collections()
        logger.info(f"Qdrant connected, {len(collections.collections)} collections")
    except Exception as e:
        logger.warning(f"Qdrant not available: {e}")

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

    # Wire up search module with initialized backends
    search_module.init(_qdrant, _meili, app.state.http_client)

    yield

    if _redis:
        await _redis.aclose()
    if _qdrant:
        await _qdrant.close()
    await app.state.http_client.aclose()

    logger.info("Memory service stopped")


app = FastAPI(
    title="Local-System Memory",
    version="0.2.0",
    lifespan=lifespan,
)

# Include hybrid search / ingestion router (merged from RAG service)
app.include_router(search_module.router)


@app.get("/health")
async def health() -> dict:
    backends = {}
    if _redis:
        try:
            await _redis.ping()
            backends["redis"] = "ok"
        except Exception:
            backends["redis"] = "error"
    if _qdrant:
        backends["qdrant"] = "ok"
    if _meili:
        backends["meilisearch"] = "ok"
    return {
        **HealthResponse(
            service="memory",
            node=settings.node.name.value,
            uptime_seconds=time.time() - app.state.start_time,
        ).model_dump(),
        "backends": backends,
    }


# =============================================================================
# Working Memory (Redis — volatile, fast access)
# =============================================================================


@app.get("/v1/memory/working")
async def get_working_context() -> WorkingContext:
    """Get current working memory state."""
    if not _redis:
        raise HTTPException(status_code=503, detail="Redis not available")

    import json

    raw = await _redis.get("local_system:working_context")
    if raw:
        return WorkingContext.model_validate_json(raw)
    return WorkingContext()


@app.put("/v1/memory/working")
async def update_working_context(ctx: WorkingContext) -> dict:
    """Update the working memory context."""
    if not _redis:
        raise HTTPException(status_code=503, detail="Redis not available")

    await _redis.set("local_system:working_context", ctx.model_dump_json())
    logger.info("Working context updated", extra={"task": ctx.active_task})
    return {"status": "updated"}


# =============================================================================
# Episodic Memory (Qdrant — timestamped events with embeddings)
# =============================================================================


@app.post("/v1/memory/episodic")
async def store_episode(event: EpisodicEvent) -> dict:
    """Store an episodic memory event."""
    if not _qdrant:
        raise HTTPException(status_code=503, detail="Qdrant not available")

    from qdrant_client.models import PointStruct

    if not event.id:
        event.id = generate_id("ep")

    point = PointStruct(
        id=abs(hash(event.id)) % (2**63),
        vector=event.embedding or [0.0] * settings.rag.embedding_dimensions,
        payload={
            "id": event.id,
            "event_type": event.event_type,
            "summary": event.summary,
            "details": event.details,
            "outcome": event.outcome,
            "timestamp": event.timestamp.isoformat(),
            "tier": MemoryTier.EPISODIC.value,
        },
    )

    await _qdrant.upsert(collection_name="episodic", points=[point])
    logger.info(f"Episodic memory stored: {event.event_type}", extra={"id": event.id})
    return {"status": "stored", "id": event.id}


@app.get("/v1/memory/episodic")
async def list_episodes(limit: int = 20) -> list[dict]:
    """List recent episodic memories."""
    if not _qdrant:
        raise HTTPException(status_code=503, detail="Qdrant not available")

    results = await _qdrant.scroll(
        collection_name="episodic",
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )

    episodes = []
    for point in results[0]:
        if point.payload:
            episodes.append(point.payload)
    return episodes


# =============================================================================
# Search across memory tiers
# =============================================================================


@app.post("/v1/memory/search")
async def search_memory(req: MemorySearchRequest) -> MemorySearchResponse:
    """Search across memory tiers using semantic similarity."""
    if not _qdrant:
        raise HTTPException(status_code=503, detail="Qdrant not available")

    # Get query embedding
    try:
        query_vector = await _get_query_embedding(req.query)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Embedding failed: {e}") from e

    tier_to_collection = {
        MemoryTier.EPISODIC: "episodic",
        MemoryTier.RESOURCE: "resources",
        MemoryTier.KNOWLEDGE_VAULT: "knowledge_vault",
    }

    tiers = req.tiers or [MemoryTier.EPISODIC, MemoryTier.RESOURCE, MemoryTier.KNOWLEDGE_VAULT]
    all_results: list[MemoryEntry] = []

    for tier in tiers:
        collection = tier_to_collection.get(tier)
        if not collection:
            continue
        try:
            results = await _qdrant.search(
                collection_name=collection,
                query_vector=query_vector,
                limit=req.top_k,
                score_threshold=req.score_threshold,
            )
            for r in results:
                payload = r.payload or {}
                all_results.append(
                    MemoryEntry(
                        id=payload.get("id", str(r.id)),
                        tier=tier,
                        content=payload.get("summary", payload.get("content", "")),
                        metadata=payload,
                        confidence=r.score,
                    )
                )
        except Exception:
            continue

    all_results.sort(key=lambda x: x.confidence, reverse=True)

    return MemorySearchResponse(
        results=all_results[: req.top_k],
        query=req.query,
        total=len(all_results),
    )


# =============================================================================
# Memory consolidation (background task)
# =============================================================================


@app.post("/v1/memory/consolidate")
async def trigger_consolidation() -> dict:
    """Trigger memory consolidation — distill episodic into semantic knowledge."""
    logger.info("Memory consolidation triggered")
    return {"status": "consolidation_queued"}


# =============================================================================
# Helpers
# =============================================================================


async def _get_query_embedding(query: str) -> list[float]:
    """Get embedding for a query string via vLLM."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.inference.vllm_embedding_host}/v1/embeddings",
            json={"model": settings.rag.embedding_model, "input": [query]},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
