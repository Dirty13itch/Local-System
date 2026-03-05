"""Memory Service — 6-tier cognitive memory system + hybrid search.

Implements the memory architecture inspired by human cognition:
  1. Working    — Active context, current task state (Redis)
  2. Episodic   — What happened when (Qdrant + timestamps)
  3. Semantic   — Knowledge graph entities and relationships (Neo4j)
  4. Procedural — How to do things (PostgreSQL, versioned)
  5. Resource   — Ingested documents, code, papers (Qdrant + Meilisearch)
  6. Vault      — Validated high-confidence facts (PostgreSQL + Qdrant)

Also provides hybrid search (Qdrant vector + Meilisearch BM25) and document
ingestion — merged from the former RAG service.

Runs on DEV. Memory consolidation happens during idle periods.
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
    SemanticEntity,
    SemanticRelation,
    WorkingContext,
)
from local_system.utils import generate_id, setup_logging

from . import search as search_module
from .consolidation import ConsolidationPipeline
from .tiers.working import WorkingTier
from .tiers.episodic import EpisodicTier
from .tiers.semantic import SemanticTier
from .tiers.procedural import ProceduralTier
from .tiers.resource import ResourceTier
from .tiers.vault import VaultTier

settings = get_settings()
logger = setup_logging("memory", settings)

# --- Tier instances ---
_working = WorkingTier()
_episodic = EpisodicTier()
_semantic = SemanticTier()
_procedural = ProceduralTier()
_resource = ResourceTier()
_vault = VaultTier()
_consolidation: ConsolidationPipeline | None = None

# Legacy references for search module compatibility
_qdrant = None
_meili = None


async def _get_embedding(text: str) -> list[float]:
    """Get embedding for a text string via vLLM."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.inference.vllm_embedding_host}/v1/embeddings",
            json={"model": settings.rag.embedding_model, "input": [text]},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _qdrant, _meili, _consolidation

    logger.info("Memory service starting — initializing 6 tiers")
    app.state.start_time = time.time()
    app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))

    # --- Initialize tiers ---

    # Working (Redis)
    await _working.init()

    # Qdrant client (shared by episodic, resource, vault)
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

    # Meilisearch (shared by resource tier and search module)
    try:
        import meilisearch
        _meili = meilisearch.Client(settings.meilisearch.url, settings.meilisearch.key)
        _meili.health()
        logger.info("Meilisearch connected for BM25 search")
    except Exception as e:
        logger.warning(f"Meilisearch not available: {e}")

    # Episodic (Qdrant)
    await _episodic.init(qdrant_client=_qdrant)

    # Semantic (Neo4j)
    await _semantic.init()

    # Procedural (PostgreSQL)
    await _procedural.init()

    # Resource (Qdrant + Meilisearch)
    await _resource.init(qdrant_client=_qdrant, meili_client=_meili)

    # Vault (PostgreSQL + Qdrant)
    await _vault.init(qdrant_client=_qdrant)

    # Wire up search module with initialized backends
    search_module.init(_qdrant, _meili, app.state.http_client)

    # Initialize consolidation pipeline
    _consolidation = ConsolidationPipeline(
        working=_working,
        episodic=_episodic,
        semantic=_semantic,
        vault=_vault,
        get_embedding=_get_embedding,
    )

    tier_status = {
        "working": _working.ready,
        "episodic": _episodic.ready,
        "semantic": _semantic.ready,
        "procedural": _procedural.ready,
        "resource": _resource.ready,
        "vault": _vault.ready,
    }
    ready_count = sum(1 for v in tier_status.values() if v)
    logger.info(f"Memory service ready — {ready_count}/6 tiers initialized: {tier_status}")

    yield

    # --- Shutdown ---
    await _working.close()
    await _semantic.close()
    await _procedural.close()
    await _vault.close()
    if _qdrant:
        await _qdrant.close()
    await app.state.http_client.aclose()

    logger.info("Memory service stopped")


app = FastAPI(
    title="Local-System Memory",
    version="0.3.0",
    lifespan=lifespan,
)

# Include hybrid search / ingestion router (merged from RAG service)
app.include_router(search_module.router)


# =============================================================================
# Health
# =============================================================================


@app.get("/health")
async def health() -> dict:
    tiers = {}
    for name, tier in [
        ("working", _working), ("episodic", _episodic),
        ("semantic", _semantic), ("procedural", _procedural),
        ("resource", _resource), ("vault", _vault),
    ]:
        tiers[name] = await tier.health()

    backends = {}
    if _qdrant:
        backends["qdrant"] = "ok"
    if _meili:
        backends["meilisearch"] = "ok"

    return {
        **HealthResponse(
            service="memory",
            version="0.3.0",
            node=settings.node.name.value,
            uptime_seconds=time.time() - app.state.start_time,
        ).model_dump(),
        "tiers": tiers,
        "backends": backends,
    }


# =============================================================================
# Working Memory (Redis)
# =============================================================================


@app.get("/v1/memory/working")
async def get_working_context() -> WorkingContext:
    """Get current working memory state."""
    return await _working.get_context()


@app.put("/v1/memory/working")
async def update_working_context(ctx: WorkingContext) -> dict:
    """Update the working memory context."""
    await _working.set_context(ctx)
    logger.info("Working context updated", extra={"task": ctx.active_task})
    return {"status": "updated"}


@app.post("/v1/memory/working/session")
async def store_session(session_id: str, data: dict, ttl: int = 7200) -> dict:
    """Store session-scoped data."""
    await _working.set_session(session_id, data, ttl)
    return {"status": "stored", "session_id": session_id}


@app.get("/v1/memory/working/session/{session_id}")
async def get_session(session_id: str) -> dict:
    """Retrieve session-scoped data."""
    data = await _working.get_session(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return data


# =============================================================================
# Episodic Memory (Qdrant)
# =============================================================================


@app.post("/v1/memory/episodic")
async def store_episode(event: EpisodicEvent) -> dict:
    """Store an episodic memory event."""
    if not event.id:
        event.id = generate_id("ep")

    # Auto-generate embedding if not provided
    if not event.embedding:
        try:
            event.embedding = await _get_embedding(event.summary)
        except Exception as e:
            logger.warning(f"Auto-embedding failed: {e}")

    entry_id = await _episodic.store_event(event)
    return {"status": "stored", "id": entry_id}


@app.get("/v1/memory/episodic")
async def list_episodes(limit: int = 20) -> list[dict]:
    """List recent episodic memories."""
    return await _episodic.list_recent(limit=limit)


# =============================================================================
# Semantic Memory (Neo4j)
# =============================================================================


@app.post("/v1/memory/semantic/entity")
async def store_entity(entity: SemanticEntity) -> dict:
    """Store an entity in the knowledge graph."""
    entry_id = await _semantic.store_entity(entity)
    return {"status": "stored", "id": entry_id}


@app.post("/v1/memory/semantic/relation")
async def store_relation(relation: SemanticRelation) -> dict:
    """Create a relationship between entities."""
    await _semantic.store_relation(relation)
    return {"status": "stored"}


@app.get("/v1/memory/semantic/neighbors/{entity_id}")
async def get_neighbors(entity_id: str, depth: int = 1) -> list[dict]:
    """Get entity neighborhood in the knowledge graph."""
    return await _semantic.get_neighbors(entity_id, depth=depth)


# =============================================================================
# Procedural Memory (PostgreSQL)
# =============================================================================


@app.post("/v1/memory/procedural")
async def store_procedure(entry: MemoryEntry) -> dict:
    """Store a procedural memory (how-to pattern)."""
    entry.tier = MemoryTier.PROCEDURAL
    entry_id = await _procedural.store(entry)
    return {"status": "stored", "id": entry_id}


@app.get("/v1/memory/procedural/{task_type}")
async def get_procedures(task_type: str, top_k: int = 5) -> list[dict]:
    """Find procedures for a task type."""
    entries = await _procedural.search_by_task_type(task_type, top_k=top_k)
    return [e.model_dump() for e in entries]


@app.post("/v1/memory/procedural/{entry_id}/outcome")
async def record_outcome(entry_id: str, success: bool = True) -> dict:
    """Record whether a procedure succeeded or failed."""
    await _procedural.record_outcome(entry_id, success)
    return {"status": "recorded", "success": success}


# =============================================================================
# Vault (PostgreSQL + Qdrant)
# =============================================================================


@app.post("/v1/memory/vault")
async def store_vault_fact(entry: MemoryEntry) -> dict:
    """Store a validated fact in the knowledge vault."""
    entry.tier = MemoryTier.KNOWLEDGE_VAULT
    if not entry.embedding:
        try:
            entry.embedding = await _get_embedding(entry.content)
        except Exception:
            pass
    entry_id = await _vault.store(entry)
    return {"status": "stored", "id": entry_id}


# =============================================================================
# Cross-tier search
# =============================================================================


@app.post("/v1/memory/search")
async def search_memory(req: MemorySearchRequest) -> MemorySearchResponse:
    """Search across memory tiers using semantic similarity."""
    try:
        query_embedding = await _get_embedding(req.query)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Embedding failed: {e}") from e

    tiers = req.tiers or [
        MemoryTier.EPISODIC,
        MemoryTier.RESOURCE,
        MemoryTier.KNOWLEDGE_VAULT,
        MemoryTier.PROCEDURAL,
    ]

    tier_map = {
        MemoryTier.WORKING: _working,
        MemoryTier.EPISODIC: _episodic,
        MemoryTier.SEMANTIC: _semantic,
        MemoryTier.PROCEDURAL: _procedural,
        MemoryTier.RESOURCE: _resource,
        MemoryTier.KNOWLEDGE_VAULT: _vault,
    }

    all_results: list[MemoryEntry] = []
    for tier_enum in tiers:
        tier = tier_map.get(tier_enum)
        if not tier or not tier.ready:
            continue
        try:
            results = await tier.search(
                req.query,
                embedding=query_embedding,
                top_k=req.top_k,
            )
            all_results.extend(results)
        except Exception as e:
            logger.warning(f"Search failed on {tier_enum.value}: {e}")

    all_results.sort(key=lambda x: x.confidence, reverse=True)

    return MemorySearchResponse(
        results=all_results[:req.top_k],
        query=req.query,
        total=len(all_results),
    )


# =============================================================================
# Generic store/retrieve (any tier)
# =============================================================================


@app.post("/v1/memory/store")
async def store_memory(entry: MemoryEntry) -> dict:
    """Store a memory in the specified tier."""
    tier_map = {
        MemoryTier.WORKING: _working,
        MemoryTier.EPISODIC: _episodic,
        MemoryTier.SEMANTIC: _semantic,
        MemoryTier.PROCEDURAL: _procedural,
        MemoryTier.RESOURCE: _resource,
        MemoryTier.KNOWLEDGE_VAULT: _vault,
    }
    tier = tier_map.get(entry.tier)
    if not tier or not tier.ready:
        raise HTTPException(status_code=503, detail=f"Tier {entry.tier.value} not available")

    if not entry.id:
        entry.id = generate_id("mem")

    # Auto-embed if needed and tier uses vectors
    if not entry.embedding and entry.tier in (
        MemoryTier.EPISODIC, MemoryTier.RESOURCE, MemoryTier.KNOWLEDGE_VAULT
    ):
        try:
            entry.embedding = await _get_embedding(entry.content)
        except Exception:
            pass

    entry_id = await tier.store(entry)
    return {"status": "stored", "id": entry_id, "tier": entry.tier.value}


@app.get("/v1/memory/{tier_name}/{entry_id}")
async def retrieve_memory(tier_name: str, entry_id: str) -> MemoryEntry:
    """Retrieve a memory by tier and ID."""
    try:
        tier_enum = MemoryTier(tier_name)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown tier: {tier_name}")

    tier_map = {
        MemoryTier.WORKING: _working,
        MemoryTier.EPISODIC: _episodic,
        MemoryTier.SEMANTIC: _semantic,
        MemoryTier.PROCEDURAL: _procedural,
        MemoryTier.RESOURCE: _resource,
        MemoryTier.KNOWLEDGE_VAULT: _vault,
    }
    tier = tier_map.get(tier_enum)
    if not tier or not tier.ready:
        raise HTTPException(status_code=503, detail=f"Tier {tier_name} not available")

    entry = await tier.retrieve(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Memory not found")
    return entry


# =============================================================================
# Consolidation
# =============================================================================


@app.post("/v1/memory/consolidate")
async def trigger_consolidation() -> dict:
    """Trigger memory consolidation — promote memories between tiers."""
    if not _consolidation:
        raise HTTPException(status_code=503, detail="Consolidation not initialized")
    stats = await _consolidation.run_full()
    return {"status": "completed", **stats}


# =============================================================================
# Stats
# =============================================================================


@app.get("/v1/memory/stats")
async def memory_stats() -> dict:
    """Get memory tier statistics."""
    stats = {}
    for name, tier in [
        ("working", _working), ("episodic", _episodic),
        ("semantic", _semantic), ("procedural", _procedural),
        ("resource", _resource), ("vault", _vault),
    ]:
        stats[name] = {
            "ready": tier.ready,
            "count": await tier.count() if tier.ready else 0,
            "health": await tier.health(),
        }
    return stats
