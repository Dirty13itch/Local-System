"""Episodic Memory — Qdrant-backed timestamped events.

Stores what happened and when: conversations, task outcomes, discoveries,
errors, feedback. Each event has an embedding for semantic retrieval and
timestamps for temporal queries.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from local_system.config import get_settings
from local_system.models import EpisodicEvent, MemoryEntry, MemoryTier
from local_system.utils import generate_id

from .base import BaseTier

logger = logging.getLogger("memory.tiers.episodic")

COLLECTION = "episodic"


class EpisodicTier(BaseTier):
    tier = MemoryTier.EPISODIC

    def __init__(self) -> None:
        self._qdrant = None
        self._settings = get_settings()

    async def init(self, qdrant_client=None) -> None:
        """Initialize with an existing Qdrant client or create one."""
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
            self._ready = True
            logger.info("Episodic tier initialized (Qdrant)")
        except Exception as e:
            logger.warning(f"Episodic tier init failed: {e}")

    async def _ensure_collection(self) -> None:
        """Create the episodic collection if it doesn't exist."""
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
            logger.info(f"Created Qdrant collection: {COLLECTION}")

    async def close(self) -> None:
        # Qdrant client lifecycle managed by memory main.py
        pass

    async def store(self, entry: MemoryEntry) -> str:
        if not self._qdrant:
            raise RuntimeError("Qdrant not available")
        from qdrant_client.models import PointStruct

        if not entry.id:
            entry.id = generate_id("ep")

        vector = entry.embedding or [0.0] * self._settings.rag.embedding_dimensions
        point = PointStruct(
            id=abs(hash(entry.id)) % (2**63),
            vector=vector,
            payload={
                "id": entry.id,
                "content": entry.content,
                "tier": MemoryTier.EPISODIC.value,
                "source": entry.source,
                "tags": entry.tags,
                "confidence": entry.confidence,
                "created_at": entry.created_at.isoformat(),
                "metadata": entry.metadata,
            },
        )
        await self._qdrant.upsert(collection_name=COLLECTION, points=[point])
        return entry.id

    async def store_event(self, event: EpisodicEvent) -> str:
        """Store a structured episodic event."""
        if not self._qdrant:
            raise RuntimeError("Qdrant not available")
        from qdrant_client.models import PointStruct

        if not event.id:
            event.id = generate_id("ep")

        vector = event.embedding or [0.0] * self._settings.rag.embedding_dimensions
        point = PointStruct(
            id=abs(hash(event.id)) % (2**63),
            vector=vector,
            payload={
                "id": event.id,
                "event_type": event.event_type,
                "summary": event.summary,
                "details": event.details,
                "participants": event.participants,
                "outcome": event.outcome,
                "timestamp": event.timestamp.isoformat(),
                "tier": MemoryTier.EPISODIC.value,
            },
        )
        await self._qdrant.upsert(collection_name=COLLECTION, points=[point])
        logger.info(f"Episodic event stored: {event.event_type}", extra={"id": event.id})
        return event.id

    async def retrieve(self, entry_id: str) -> MemoryEntry | None:
        if not self._qdrant:
            return None
        results = await self._qdrant.scroll(
            collection_name=COLLECTION,
            scroll_filter={
                "must": [{"key": "id", "match": {"value": entry_id}}]
            },
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        points = results[0]
        if not points:
            return None
        payload = points[0].payload or {}
        return MemoryEntry(
            id=payload.get("id", entry_id),
            tier=MemoryTier.EPISODIC,
            content=payload.get("content", "") or payload.get("text", "") or payload.get("summary", ""),
            metadata=payload.get("metadata", payload),
            source=payload.get("source", ""),
            confidence=payload.get("confidence", 1.0),
            tags=payload.get("tags", []),
        )

    async def search(
        self,
        query: str,
        *,
        embedding: list[float] | None = None,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[MemoryEntry]:
        if not self._qdrant or not embedding:
            return []

        search_filter = None
        if filters:
            conditions = []
            if "event_type" in filters:
                conditions.append({"key": "event_type", "match": {"value": filters["event_type"]}})
            if "time_after" in filters:
                conditions.append({"key": "timestamp", "range": {"gte": filters["time_after"]}})
            if "time_before" in filters:
                conditions.append({"key": "timestamp", "range": {"lte": filters["time_before"]}})
            if conditions:
                search_filter = {"must": conditions}

        hits_resp = await self._qdrant.query_points(
            collection_name=COLLECTION,
            query=embedding,
            limit=top_k,
            query_filter=search_filter,
        )
        hits = hits_resp.points

        results = []
        for hit in hits:
            payload = hit.payload or {}
            results.append(MemoryEntry(
                id=payload.get("id", str(hit.id)),
                tier=MemoryTier.EPISODIC,
                content=payload.get("content", "") or payload.get("text", "") or payload.get("summary", ""),
                metadata=payload.get("metadata", payload),
                source=payload.get("source", ""),
                confidence=hit.score,
                tags=payload.get("tags", []),
            ))
        return results

    async def list_recent(self, limit: int = 20) -> list[dict]:
        """List recent episodic memories (scroll, no vector needed)."""
        if not self._qdrant:
            return []
        results = await self._qdrant.scroll(
            collection_name=COLLECTION,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [p.payload for p in results[0] if p.payload]

    async def delete(self, entry_id: str) -> bool:
        if not self._qdrant:
            return False
        point_id = abs(hash(entry_id)) % (2**63)
        await self._qdrant.delete(
            collection_name=COLLECTION,
            points_selector={"points": [point_id]},
        )
        return True

    async def count(self) -> int:
        if not self._qdrant:
            return 0
        try:
            info = await self._qdrant.get_collection(COLLECTION)
            return info.points_count or 0
        except Exception:
            return 0
