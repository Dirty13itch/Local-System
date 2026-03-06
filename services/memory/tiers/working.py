"""Working Memory — Redis-backed volatile context.

Fast key-value store for active conversation state, session data,
and short-lived context. TTL-based expiry. No embeddings needed.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from local_system.config import get_settings
from local_system.models import MemoryEntry, MemoryTier, WorkingContext

from .base import BaseTier

logger = logging.getLogger("memory.tiers.working")

# Redis key prefix
PREFIX = "ls:memory:working"


class WorkingTier(BaseTier):
    tier = MemoryTier.WORKING

    def __init__(self) -> None:
        self._redis = None
        self._settings = get_settings()

    async def init(self) -> None:
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                self._settings.redis.url, decode_responses=True
            )
            await self._redis.ping()
            self._ready = True
            logger.info("Working tier initialized (Redis)")
        except Exception as e:
            logger.warning(f"Working tier init failed: {e}")

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()

    async def store(self, entry: MemoryEntry) -> str:
        if not self._redis:
            raise RuntimeError("Redis not available")
        key = f"{PREFIX}:{entry.id}"
        data = entry.model_dump_json()
        ttl = 3600  # 1 hour default
        if entry.expires_at:
            exp = entry.expires_at.replace(tzinfo=timezone.utc) if entry.expires_at.tzinfo is None else entry.expires_at
            ttl = max(1, int((exp - datetime.now(timezone.utc)).total_seconds()))
        await self._redis.setex(key, ttl, data)
        logger.debug(f"Working memory stored: {entry.id} (TTL={ttl}s)")
        return entry.id

    async def retrieve(self, entry_id: str) -> MemoryEntry | None:
        if not self._redis:
            return None
        raw = await self._redis.get(f"{PREFIX}:{entry_id}")
        if raw:
            return MemoryEntry.model_validate_json(raw)
        return None

    async def search(
        self,
        query: str,
        *,
        embedding: list[float] | None = None,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[MemoryEntry]:
        """Scan working memory keys and do simple text matching."""
        if not self._redis:
            return []
        results = []
        query_lower = query.lower()
        async for key in self._redis.scan_iter(f"{PREFIX}:*", count=100):
            raw = await self._redis.get(key)
            if not raw:
                continue
            entry = MemoryEntry.model_validate_json(raw)
            if query_lower in entry.content.lower():
                entry.confidence = 1.0
                results.append(entry)
                if len(results) >= top_k:
                    break
        return results

    async def delete(self, entry_id: str) -> bool:
        if not self._redis:
            return False
        return bool(await self._redis.delete(f"{PREFIX}:{entry_id}"))

    async def count(self) -> int:
        if not self._redis:
            return 0
        count = 0
        async for _ in self._redis.scan_iter(f"{PREFIX}:*", count=100):
            count += 1
        return count

    # --- Working-context convenience methods ---

    async def get_context(self) -> WorkingContext:
        """Get the active working context."""
        if not self._redis:
            return WorkingContext()
        raw = await self._redis.get(f"{PREFIX}:__context__")
        if raw:
            return WorkingContext.model_validate_json(raw)
        return WorkingContext()

    async def set_context(self, ctx: WorkingContext) -> None:
        """Update the active working context."""
        if not self._redis:
            raise RuntimeError("Redis not available")
        await self._redis.set(f"{PREFIX}:__context__", ctx.model_dump_json())

    async def set_session(self, session_id: str, data: dict[str, Any], ttl: int = 7200) -> None:
        """Store a session-scoped value (2-hour default TTL)."""
        if not self._redis:
            raise RuntimeError("Redis not available")
        await self._redis.setex(
            f"{PREFIX}:session:{session_id}", ttl, json.dumps(data)
        )

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve a session-scoped value."""
        if not self._redis:
            return None
        raw = await self._redis.get(f"{PREFIX}:session:{session_id}")
        return json.loads(raw) if raw else None

    async def health(self) -> str:
        if not self._redis:
            return "not_initialized"
        try:
            await self._redis.ping()
            return "ok"
        except Exception:
            return "error"
