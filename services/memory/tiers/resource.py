"""Resource Memory — Qdrant + Meilisearch ingested documents.

Stores chunked, embedded documents: code files, papers, manuals, configs.
Uses Qdrant for vector search and Meilisearch for BM25 full-text search.
Hybrid search combines both with configurable alpha weighting.

Note: The hybrid search/ingestion endpoints are in search.py (the merged
RAG module). This tier class provides the BaseTier interface for cross-tier
operations.
"""

from __future__ import annotations

import logging
from typing import Any

from local_system.config import get_settings
from local_system.models import MemoryEntry, MemoryTier
from local_system.utils import generate_id

from .base import BaseTier

logger = logging.getLogger("memory.tiers.resource")

COLLECTION = "resources"


class ResourceTier(BaseTier):
    tier = MemoryTier.RESOURCE

    def __init__(self) -> None:
        self._qdrant = None
        self._meili = None
        self._settings = get_settings()

    async def init(self, qdrant_client=None, meili_client=None) -> None:
        """Initialize with existing clients (shared with search module)."""
        try:
            if qdrant_client:
                self._qdrant = qdrant_client
            else:
                from qdrant_client import AsyncQdrantClient
                self._qdrant = AsyncQdrantClient(
                    host=self._settings.qdrant.host,
                    port=self._settings.qdrant.port,
                )
            self._meili = meili_client
            await self._ensure_collection()
            self._ready = True
            logger.info("Resource tier initialized (Qdrant + Meilisearch)")
        except Exception as e:
            logger.warning(f"Resource tier init failed: {e}")

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
            logger.info(f"Created Qdrant collection: {COLLECTION}")

    async def close(self) -> None:
        pass  # Lifecycle managed by memory main.py

    async def store(self, entry: MemoryEntry) -> str:
        """Store a resource chunk with embedding."""
        if not self._qdrant:
            raise RuntimeError("Qdrant not available")
        from qdrant_client.models import PointStruct

        if not entry.id:
            entry.id = generate_id("res")

        vector = entry.embedding or [0.0] * self._settings.rag.embedding_dimensions
        point = PointStruct(
            id=abs(hash(entry.id)) % (2**63),
            vector=vector,
            payload={
                "id": entry.id,
                "content": entry.content,
                "source": entry.source,
                "tier": MemoryTier.RESOURCE.value,
                "tags": entry.tags,
                "confidence": entry.confidence,
                "created_at": entry.created_at.isoformat(),
                "metadata": entry.metadata,
            },
        )
        await self._qdrant.upsert(collection_name=COLLECTION, points=[point])

        # Also index in Meilisearch for BM25
        if self._meili:
            try:
                index = self._meili.index(COLLECTION)
                index.add_documents([{
                    "id": entry.id,
                    "content": entry.content,
                    "source": entry.source,
                    "tags": ",".join(entry.tags),
                }])
            except Exception as e:
                logger.warning(f"Meilisearch indexing failed: {e}")

        return entry.id

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
            tier=MemoryTier.RESOURCE,
            content=payload.get("content", ""),
            metadata=payload.get("metadata", {}),
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
        """Vector search on resource chunks."""
        if not self._qdrant or not embedding:
            return []

        search_filter = None
        if filters:
            conditions = []
            if "source" in filters:
                conditions.append({"key": "source", "match": {"value": filters["source"]}})
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
                tier=MemoryTier.RESOURCE,
                content=payload.get("content", ""),
                metadata=payload.get("metadata", {}),
                source=payload.get("source", ""),
                confidence=hit.score,
                tags=payload.get("tags", []),
            ))
        return results

    async def delete(self, entry_id: str) -> bool:
        if not self._qdrant:
            return False
        point_id = abs(hash(entry_id)) % (2**63)
        await self._qdrant.delete(
            collection_name=COLLECTION,
            points_selector={"points": [point_id]},
        )
        if self._meili:
            try:
                self._meili.index(COLLECTION).delete_document(entry_id)
            except Exception:
                pass
        return True

    async def count(self) -> int:
        if not self._qdrant:
            return 0
        try:
            info = await self._qdrant.get_collection(COLLECTION)
            return info.points_count or 0
        except Exception:
            return 0
