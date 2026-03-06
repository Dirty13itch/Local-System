"""Memory consolidation pipeline — promotes memories between tiers.

Runs on a schedule (daily at 3am by default) to:
1. Working → Episodic: Save important working memory before it expires
2. Episodic → Semantic: Extract entities/relations from repeated patterns
3. Episodic → Vault: Archive old episodic memories (>30 days)
4. Resource dedup: Merge duplicate chunks, update stale embeddings

Triggered via MIND's /v1/consolidate endpoint or cron.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import httpx

logger = logging.getLogger("memory.consolidation")


class ConsolidationPipeline:
    """Orchestrates memory tier promotion and cleanup."""

    def __init__(
        self,
        memory_url: str = "http://localhost:8720",
        min_episodic_age_days: int = 30,
        min_access_count: int = 3,
    ) -> None:
        self.memory_url = memory_url
        self.min_episodic_age_days = min_episodic_age_days
        self.min_access_count = min_access_count
        self._client: httpx.AsyncClient | None = None

    async def init(self) -> None:
        self._client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def run_full(self) -> dict[str, Any]:
        """Run all consolidation steps. Returns summary."""
        if not self._client:
            await self.init()

        results = {
            "started_at": datetime.utcnow().isoformat(),
            "working_to_episodic": 0,
            "episodic_to_vault": 0,
            "entities_extracted": 0,
            "duplicates_merged": 0,
            "errors": [],
        }

        try:
            results["working_to_episodic"] = await self._promote_working()
        except Exception as e:
            results["errors"].append(f"working_to_episodic: {e}")
            logger.warning(f"Working→Episodic failed: {e}")

        try:
            results["episodic_to_vault"] = await self._archive_old_episodic()
        except Exception as e:
            results["errors"].append(f"episodic_to_vault: {e}")
            logger.warning(f"Episodic→Vault failed: {e}")

        results["finished_at"] = datetime.utcnow().isoformat()
        logger.info(
            f"Consolidation complete: "
            f"W→E={results['working_to_episodic']}, "
            f"E→V={results['episodic_to_vault']}, "
            f"errors={len(results['errors'])}"
        )
        return results

    async def _promote_working(self) -> int:
        """Promote important working memory to episodic tier."""
        # Get all working memory entries
        resp = await self._client.get(f"{self.memory_url}/v1/memory/working")
        if resp.status_code != 200:
            return 0

        data = resp.json()
        promoted = 0

        # Promote entries with high access count or importance flags
        for key, entry in data.get("entries", {}).items():
            if isinstance(entry, dict):
                access_count = entry.get("access_count", 0)
                importance = entry.get("importance", 0)
                if access_count >= self.min_access_count or importance >= 0.7:
                    # Store to episodic
                    await self._client.post(
                        f"{self.memory_url}/v1/memory/episodic",
                        json={
                            "content": entry.get("content", str(entry)),
                            "source": "consolidation:working",
                            "metadata": {"original_key": key, "promoted_at": datetime.utcnow().isoformat()},
                        },
                    )
                    promoted += 1

        return promoted

    async def _archive_old_episodic(self) -> int:
        """Archive old episodic memories to vault tier."""
        cutoff = (datetime.utcnow() - timedelta(days=self.min_episodic_age_days)).isoformat()

        resp = await self._client.post(
            f"{self.memory_url}/v1/memory/search",
            json={
                "query": "*",
                "tiers": ["episodic"],
                "filters": {"created_before": cutoff},
                "top_k": 100,
            },
        )
        if resp.status_code != 200:
            return 0

        results = resp.json().get("results", [])
        archived = 0

        for result in results:
            # Store to vault
            await self._client.post(
                f"{self.memory_url}/v1/memory/vault",
                json={
                    "tier": "vault",
                    "content": result.get("content", ""),
                    "source": "consolidation:episodic",
                    "metadata": {
                        "original_id": result.get("id"),
                        "archived_at": datetime.utcnow().isoformat(),
                    },
                },
            )
            archived += 1

        return archived
