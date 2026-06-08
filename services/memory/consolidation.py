"""Memory consolidation pipeline — promotes memories between tiers.

Routes all writes through the Quality Gate (DEV:8790) for dedup and validation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger("memory.consolidation")

QUALITY_GATE_URL = "http://localhost:8790"


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
            "started_at": datetime.now(timezone.utc).isoformat(),
            "working_to_episodic": 0,
            "episodic_to_vault": 0,
            "entities_extracted": 0,
            "duplicates_merged": 0,
            "duplicates_skipped": 0,
            "rejected": 0,
            "errors": [],
        }

        try:
            promoted, skipped, rejected = await self._promote_working()
            results["working_to_episodic"] = promoted
            results["duplicates_skipped"] += skipped
            results["rejected"] += rejected
        except Exception as e:
            results["errors"].append(f"working_to_episodic: {e}")
            logger.warning(f"Working->Episodic failed: {e}")

        try:
            archived, skipped, rejected = await self._archive_old_episodic()
            results["episodic_to_vault"] = archived
            results["duplicates_skipped"] += skipped
            results["rejected"] += rejected
        except Exception as e:
            results["errors"].append(f"episodic_to_vault: {e}")
            logger.warning(f"Episodic->Vault failed: {e}")

        results["finished_at"] = datetime.now(timezone.utc).isoformat()
        logger.info(
            f"Consolidation complete: "
            f"W->E={results['working_to_episodic']}, "
            f"E->V={results['episodic_to_vault']}, "
            f"dupes_skipped={results['duplicates_skipped']}, "
            f"rejected={results['rejected']}, "
            f"errors={len(results['errors'])}"
        )
        return results

    async def _store_via_gate(self, content: str, collection: str, metadata: dict) -> str:
        """Store content through the Quality Gate for validation and dedup.
        
        Returns: action (STORED, DUPLICATE, ENRICHED, REJECTED)
        """
        try:
            resp = await self._client.post(
                f"{QUALITY_GATE_URL}/store",
                json={
                    "content": content,
                    "collection": collection,
                    "metadata": metadata,
                    "source_env": "production",
                },
                timeout=30.0,
            )
            if resp.status_code == 200:
                result = resp.json()
                action = result.get("action", "UNKNOWN")
                if action in ("DUPLICATE", "ENRICHED"):
                    logger.debug(f"Quality Gate: {action} for {collection} — {result.get('reason', '')[:60]}")
                return action
            else:
                logger.warning(f"Quality Gate returned {resp.status_code}, falling back to direct store")
                return "FALLBACK"
        except Exception as e:
            logger.warning(f"Quality Gate unavailable ({e}), falling back to direct store")
            return "FALLBACK"

    async def _promote_working(self) -> tuple[int, int, int]:
        """Promote important working memory to episodic tier.
        
        Returns: (promoted, skipped_dupes, rejected)
        """
        resp = await self._client.get(f"{self.memory_url}/v1/memory/working")
        if resp.status_code != 200:
            return 0, 0, 0

        data = resp.json()
        promoted = 0
        skipped = 0
        rejected = 0

        for key, entry in data.get("entries", {}).items():
            if isinstance(entry, dict):
                access_count = entry.get("access_count", 0)
                importance = entry.get("importance", 0)
                if access_count >= self.min_access_count or importance >= 0.7:
                    content = entry.get("content", str(entry))
                    metadata = {
                        "source": "consolidation:working",
                        "original_key": key,
                        "promoted_at": datetime.now(timezone.utc).isoformat(),
                    }
                    
                    action = await self._store_via_gate(content, "episodic", metadata)
                    
                    if action == "STORED":
                        promoted += 1
                    elif action in ("DUPLICATE", "ENRICHED"):
                        skipped += 1
                    elif action == "REJECTED":
                        rejected += 1
                    elif action == "FALLBACK":
                        # Quality Gate unavailable — fall back to direct store
                        await self._client.post(
                            f"{self.memory_url}/v1/memory/episodic",
                            json={"content": content, "source": "consolidation:working", "metadata": metadata},
                        )
                        promoted += 1

        return promoted, skipped, rejected

    async def _archive_old_episodic(self) -> tuple[int, int, int]:
        """Archive old episodic memories to vault tier.
        
        Returns: (archived, skipped_dupes, rejected)
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.min_episodic_age_days)).isoformat()

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
            return 0, 0, 0

        results = resp.json().get("results", [])
        archived = 0
        skipped = 0
        rejected = 0

        for result in results:
            content = result.get("content", "")
            metadata = {
                "source": "consolidation:episodic",
                "original_id": result.get("id"),
                "archived_at": datetime.now(timezone.utc).isoformat(),
            }
            
            action = await self._store_via_gate(content, "knowledge_vault", metadata)
            
            if action == "STORED":
                archived += 1
            elif action in ("DUPLICATE", "ENRICHED"):
                skipped += 1
            elif action == "REJECTED":
                rejected += 1
            elif action == "FALLBACK":
                await self._client.post(
                    f"{self.memory_url}/v1/memory/vault",
                    json={"tier": "vault", "content": content, "source": "consolidation:episodic", "metadata": metadata},
                )
                archived += 1

        return archived, skipped, rejected
