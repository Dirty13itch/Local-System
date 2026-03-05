"""Memory Consolidation Pipeline.

Promotes memories between tiers based on access patterns, age, and confidence:

  Working (volatile) --> Episodic (timestamped events)
  Episodic --> Semantic (extract entities/relations into knowledge graph)
  Episodic --> Vault (high-confidence validated facts)
  Procedural outcomes update success/failure counts

Runs as a background task during idle periods or on manual trigger.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from local_system.models import MemoryEntry, MemoryTier
from local_system.utils import generate_id

if TYPE_CHECKING:
    from .tiers.episodic import EpisodicTier
    from .tiers.semantic import SemanticTier
    from .tiers.vault import VaultTier
    from .tiers.working import WorkingTier

logger = logging.getLogger("memory.consolidation")


class ConsolidationPipeline:
    """Orchestrates memory tier promotion and maintenance."""

    def __init__(
        self,
        working: WorkingTier,
        episodic: EpisodicTier,
        semantic: SemanticTier,
        vault: VaultTier,
        get_embedding=None,
    ) -> None:
        self.working = working
        self.episodic = episodic
        self.semantic = semantic
        self.vault = vault
        self._get_embedding = get_embedding  # async callable(str) -> list[float]

    async def run_full(self) -> dict:
        """Run all consolidation steps. Returns summary stats."""
        stats = {
            "working_to_episodic": 0,
            "episodic_to_vault": 0,
            "working_expired": 0,
            "started_at": datetime.utcnow().isoformat(),
        }

        # Step 1: Expire old working memory entries
        stats["working_expired"] = await self._expire_working()

        # Step 2: Promote high-value episodic memories to vault
        stats["episodic_to_vault"] = await self._promote_episodic_to_vault()

        stats["completed_at"] = datetime.utcnow().isoformat()
        logger.info(f"Consolidation complete: {stats}")
        return stats

    async def _expire_working(self) -> int:
        """Clean up expired working memory entries."""
        if not self.working.ready:
            return 0
        # Working memory has TTL via Redis — entries auto-expire.
        # This step is a no-op for Redis but exists for future backends.
        return 0

    async def _promote_episodic_to_vault(self) -> int:
        """Promote high-confidence episodic entries to the knowledge vault."""
        if not self.episodic.ready or not self.vault.ready:
            return 0

        promoted = 0
        recent = await self.episodic.list_recent(limit=100)

        for event_data in recent:
            confidence = event_data.get("confidence", 0)
            outcome = event_data.get("outcome", "")

            # Promote if high confidence and successful outcome
            if confidence >= 0.8 and outcome in ("success", "resolved", "confirmed"):
                content = event_data.get("summary", event_data.get("content", ""))
                if not content:
                    continue

                embedding = None
                if self._get_embedding:
                    try:
                        embedding = await self._get_embedding(content)
                    except Exception:
                        pass

                vault_entry = MemoryEntry(
                    id=generate_id("vault"),
                    tier=MemoryTier.KNOWLEDGE_VAULT,
                    content=content,
                    source=f"episodic:{event_data.get('id', '')}",
                    confidence=confidence,
                    embedding=embedding,
                    metadata={
                        "category": event_data.get("event_type", "general"),
                        "provenance": [{
                            "source_tier": "episodic",
                            "source_id": event_data.get("id", ""),
                            "promoted_at": datetime.utcnow().isoformat(),
                        }],
                    },
                )

                try:
                    await self.vault.store(vault_entry)
                    promoted += 1
                except Exception as e:
                    logger.warning(f"Failed to promote to vault: {e}")

        if promoted:
            logger.info(f"Promoted {promoted} episodic memories to vault")
        return promoted

    async def store_and_classify(self, content: str, source: str = "") -> MemoryEntry:
        """Store content in the appropriate tier based on classification.

        Simple heuristic:
        - Short, actionable content -> Working
        - Event-like content with timestamps -> Episodic
        - Factual/definitional content -> Vault
        - Default -> Episodic
        """
        embedding = None
        if self._get_embedding:
            try:
                embedding = await self._get_embedding(content)
            except Exception:
                pass

        entry = MemoryEntry(
            id=generate_id("mem"),
            tier=MemoryTier.EPISODIC,
            content=content,
            source=source,
            embedding=embedding,
        )

        if len(content) < 200:
            # Short content goes to working memory
            entry.tier = MemoryTier.WORKING
            if self.working.ready:
                await self.working.store(entry)
        else:
            # Longer content goes to episodic
            entry.tier = MemoryTier.EPISODIC
            if self.episodic.ready:
                await self.episodic.store(entry)

        return entry
