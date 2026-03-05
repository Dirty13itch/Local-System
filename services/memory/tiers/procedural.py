"""Procedural Memory — PostgreSQL-backed how-to patterns.

Stores versioned patterns for how to accomplish tasks: debugging workflows,
deployment procedures, code recipes, configuration steps. Each pattern has
a task_type for retrieval and a version for evolution tracking.
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

logger = logging.getLogger("memory.tiers.procedural")

# SQL schema for procedural memory
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS procedural_memory (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    steps JSONB DEFAULT '[]',
    prerequisites JSONB DEFAULT '[]',
    tags JSONB DEFAULT '[]',
    source TEXT DEFAULT '',
    confidence FLOAT DEFAULT 1.0,
    version INT DEFAULT 1,
    success_count INT DEFAULT 0,
    failure_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_procedural_task_type ON procedural_memory(task_type);
CREATE INDEX IF NOT EXISTS idx_procedural_tags ON procedural_memory USING GIN(tags);
"""


class ProceduralTier(BaseTier):
    tier = MemoryTier.PROCEDURAL

    def __init__(self) -> None:
        self._pool = None
        self._settings = get_settings()

    async def init(self) -> None:
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
            self._ready = True
            logger.info("Procedural tier initialized (PostgreSQL)")
        except Exception as e:
            logger.warning(f"Procedural tier init failed: {e}")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    async def store(self, entry: MemoryEntry) -> str:
        if not self._pool:
            raise RuntimeError("PostgreSQL not available")
        if not entry.id:
            entry.id = generate_id("proc")

        task_type = entry.metadata.get("task_type", "general")
        title = entry.metadata.get("title", entry.content[:100])
        steps = entry.metadata.get("steps", [])
        prerequisites = entry.metadata.get("prerequisites", [])

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO procedural_memory
                    (id, task_type, title, content, steps, prerequisites,
                     tags, source, confidence)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (id) DO UPDATE SET
                    content = EXCLUDED.content,
                    steps = EXCLUDED.steps,
                    version = procedural_memory.version + 1,
                    updated_at = NOW()
                """,
                entry.id,
                task_type,
                title,
                entry.content,
                json.dumps(steps),
                json.dumps(prerequisites),
                json.dumps(entry.tags),
                entry.source,
                entry.confidence,
            )
        logger.info(f"Procedural memory stored: {title} ({task_type})")
        return entry.id

    async def retrieve(self, entry_id: str) -> MemoryEntry | None:
        if not self._pool:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM procedural_memory WHERE id = $1", entry_id
            )
            if not row:
                return None
            return self._row_to_entry(row)

    async def search(
        self,
        query: str,
        *,
        embedding: list[float] | None = None,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[MemoryEntry]:
        """Search by task_type or text content."""
        if not self._pool:
            return []

        conditions = ["(title ILIKE $1 OR content ILIKE $1)"]
        params: list[Any] = [f"%{query}%"]
        idx = 2

        if filters:
            if "task_type" in filters:
                conditions.append(f"task_type = ${idx}")
                params.append(filters["task_type"])
                idx += 1

        where = " AND ".join(conditions)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM procedural_memory WHERE {where} "
                f"ORDER BY success_count DESC, updated_at DESC LIMIT ${idx}",
                *params,
                top_k,
            )
        return [self._row_to_entry(row) for row in rows]

    async def search_by_task_type(self, task_type: str, top_k: int = 5) -> list[MemoryEntry]:
        """Find procedures for a specific task type."""
        if not self._pool:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM procedural_memory WHERE task_type = $1 "
                "ORDER BY success_count DESC, version DESC LIMIT $2",
                task_type,
                top_k,
            )
        return [self._row_to_entry(row) for row in rows]

    async def record_outcome(self, entry_id: str, success: bool) -> None:
        """Record whether a procedure succeeded or failed."""
        if not self._pool:
            return
        col = "success_count" if success else "failure_count"
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"UPDATE procedural_memory SET {col} = {col} + 1 WHERE id = $1",
                entry_id,
            )

    async def delete(self, entry_id: str) -> bool:
        if not self._pool:
            return False
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM procedural_memory WHERE id = $1", entry_id
            )
            return result == "DELETE 1"

    async def count(self) -> int:
        if not self._pool:
            return 0
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT count(*) AS c FROM procedural_memory")
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
            tier=MemoryTier.PROCEDURAL,
            content=row["content"],
            source=row["source"],
            confidence=row["confidence"],
            tags=json.loads(row["tags"]) if isinstance(row["tags"], str) else row["tags"],
            metadata={
                "task_type": row["task_type"],
                "title": row["title"],
                "steps": json.loads(row["steps"]) if isinstance(row["steps"], str) else row["steps"],
                "prerequisites": json.loads(row["prerequisites"]) if isinstance(row["prerequisites"], str) else row["prerequisites"],
                "version": row["version"],
                "success_count": row["success_count"],
                "failure_count": row["failure_count"],
            },
            created_at=row["created_at"],
        )
