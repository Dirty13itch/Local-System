"""Knowledge Vault — PostgreSQL + Qdrant validated facts archive.

Long-term storage for high-confidence, validated knowledge extracted from
episodic and semantic tiers during consolidation. Each fact has provenance
tracking (where it came from) and a confidence score.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from local_system.config import get_settings
from local_system.models import MemoryEntry, MemoryTier
from local_system.utils import generate_id

from .base import BaseTier

logger = logging.getLogger("memory.tiers.vault")

COLLECTION = "knowledge_vault"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS knowledge_vault (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    source TEXT DEFAULT '',
    provenance JSONB DEFAULT '[]',
    tags JSONB DEFAULT '[]',
    confidence FLOAT DEFAULT 1.0,
    access_count INT DEFAULT 0,
    last_accessed TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vault_category ON knowledge_vault(category);
CREATE INDEX IF NOT EXISTS idx_vault_tags ON knowledge_vault USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_vault_confidence ON knowledge_vault(confidence DESC);
"""


class VaultTier(BaseTier):
    tier = MemoryTier.KNOWLEDGE_VAULT

    def __init__(self) -> None:
        self._pool = None
        self._qdrant = None
        self._settings = get_settings()

    async def init(self, qdrant_client=None) -> None:
        """Initialize PostgreSQL for metadata + Qdrant for vector search."""
        # PostgreSQL for structured storage
        try:
            import asyncpg

            self._pool = await asyncpg.create_pool(
                host=self._settings.database.host,
                port=self._settings.database.port,
                database=self._settings.database.name,
                user=self._settings.database.user,
                password=self._settings.database.password,
                min_size=1,
                max_size=5,
            )
            async with self._pool.acquire() as conn:
                await conn.execute(SCHEMA_SQL)
            logger.info("Vault tier PostgreSQL ready")
        except Exception as e:
            logger.warning(f"Vault tier PostgreSQL init failed: {e}")

        # Qdrant for vector search on vault entries
        try:
            if qdrant_client:
                self._qdrant = qdrant_client
            else:
                from qdrant_client import AsyncQdrantClient
                self._qdrant = AsyncQdrantClient(
                    host=self._settings.qdrant.host,
                    port=self._settings.qdrant.port,
                )
            await self._ensure_collection()
        except Exception as e:
            logger.warning(f"Vault tier Qdrant init failed: {e}")

        self._ready = bool(self._pool)
        if self._ready:
            logger.info("Vault tier initialized (PostgreSQL + Qdrant)")

    async def _ensure_collection(self) -> None:
        from qdrant_client.models import Distance, VectorParams
        try:
            await self._qdrant.get_collection(COLLECTION)
        except Exception:
            await self._qdrant.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(
                    size=self._settings.rag.embedding_dimensions,
                    distance=Distance.COSINE,
                ),
            )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    async def store(self, entry: MemoryEntry) -> str:
        """Store a validated fact in both PostgreSQL and Qdrant."""
        if not self._pool:
            raise RuntimeError("PostgreSQL not available")
        if not entry.id:
            entry.id = generate_id("vault")

        category = entry.metadata.get("category", "general")
        provenance = entry.metadata.get("provenance", [])

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO knowledge_vault
                    (id, content, category, source, provenance, tags, confidence)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (id) DO UPDATE SET
                    content = EXCLUDED.content,
                    confidence = GREATEST(knowledge_vault.confidence, EXCLUDED.confidence),
                    updated_at = NOW()
                """,
                entry.id,
                entry.content,
                category,
                entry.source,
                json.dumps(provenance),
                json.dumps(entry.tags),
                entry.confidence,
            )

        # Also store vector for semantic search
        if self._qdrant and entry.embedding:
            from qdrant_client.models import PointStruct
            point = PointStruct(
                id=abs(hash(entry.id)) % (2**63),
                vector=entry.embedding,
                payload={
                    "id": entry.id,
                    "content": entry.content,
                    "category": category,
                    "source": entry.source,
                    "confidence": entry.confidence,
                    "tier": MemoryTier.KNOWLEDGE_VAULT.value,
                },
            )
            await self._qdrant.upsert(collection_name=COLLECTION, points=[point])

        logger.info(f"Vault fact stored: {entry.id} ({category})")
        return entry.id

    async def retrieve(self, entry_id: str) -> MemoryEntry | None:
        if not self._pool:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM knowledge_vault WHERE id = $1", entry_id
            )
            if not row:
                return None
            # Record access
            await conn.execute(
                "UPDATE knowledge_vault SET access_count = access_count + 1, "
                "last_accessed = NOW() WHERE id = $1",
                entry_id,
            )
            return self._row_to_entry(row)

    async def search(
        self,
        query: str,
        *,
        embedding: list[float] | None = None,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[MemoryEntry]:
        """Search vault — vector search if embedding provided, else text search."""
        # Try vector search first
        if self._qdrant and embedding:
            search_filter = None
            if filters and "category" in filters:
                search_filter = {"must": [{"key": "category", "match": {"value": filters["category"]}}]}

            hits_resp = await self._qdrant.query_points(
                collection_name=COLLECTION,
                query=embedding,
                limit=top_k,
                query_filter=search_filter,
            )
            hits = hits_resp.points
            if hits:
                results = []
                for hit in hits:
                    payload = hit.payload or {}
                    results.append(MemoryEntry(
                        id=payload.get("id", str(hit.id)),
                        tier=MemoryTier.KNOWLEDGE_VAULT,
                        content=payload.get("content", ""),
                        metadata=payload,
                        source=payload.get("source", ""),
                        confidence=hit.score,
                    ))
                return results

        # Fallback to PostgreSQL text search
        if not self._pool:
            return []

        conditions = ["content ILIKE $1"]
        params: list[Any] = [f"%{query}%"]
        idx = 2

        if filters and "category" in filters:
            conditions.append(f"category = ${idx}")
            params.append(filters["category"])
            idx += 1

        where = " AND ".join(conditions)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM knowledge_vault WHERE {where} "
                f"ORDER BY confidence DESC, access_count DESC LIMIT ${idx}",
                *params,
                top_k,
            )
        return [self._row_to_entry(row) for row in rows]

    async def delete(self, entry_id: str) -> bool:
        if not self._pool:
            return False
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM knowledge_vault WHERE id = $1", entry_id
            )
        if self._qdrant:
            try:
                point_id = abs(hash(entry_id)) % (2**63)
                await self._qdrant.delete(
                    collection_name=COLLECTION,
                    points_selector={"points": [point_id]},
                )
            except Exception:
                pass
        return result == "DELETE 1"

    async def count(self) -> int:
        if not self._pool:
            return 0
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT count(*) AS c FROM knowledge_vault")
            return row["c"] if row else 0

    async def health(self) -> str:
        if not self._pool:
            return "not_initialized"
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return "ok"
        except Exception:
            return "error"

    @staticmethod
    def _row_to_entry(row) -> MemoryEntry:
        return MemoryEntry(
            id=row["id"],
            tier=MemoryTier.KNOWLEDGE_VAULT,
            content=row["content"],
            source=row["source"],
            confidence=row["confidence"],
            tags=json.loads(row["tags"]) if isinstance(row["tags"], str) else row["tags"],
            metadata={
                "category": row["category"],
                "provenance": json.loads(row["provenance"]) if isinstance(row["provenance"], str) else row["provenance"],
                "access_count": row["access_count"],
            },
            created_at=row["created_at"],
        )
