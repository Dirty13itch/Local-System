"""Base interface for all memory tiers."""

from __future__ import annotations

import abc
from typing import Any

from local_system.models import MemoryEntry, MemoryTier


class BaseTier(abc.ABC):
    """Abstract base for a memory tier."""

    tier: MemoryTier
    _ready: bool = False

    @abc.abstractmethod
    async def init(self) -> None:
        """Initialize backend connections."""

    @abc.abstractmethod
    async def close(self) -> None:
        """Clean up connections."""

    @property
    def ready(self) -> bool:
        return self._ready

    @abc.abstractmethod
    async def store(self, entry: MemoryEntry) -> str:
        """Store a memory entry. Returns the entry ID."""

    @abc.abstractmethod
    async def retrieve(self, entry_id: str) -> MemoryEntry | None:
        """Retrieve a single memory by ID."""

    @abc.abstractmethod
    async def search(
        self,
        query: str,
        *,
        embedding: list[float] | None = None,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[MemoryEntry]:
        """Search this tier. Provide embedding for vector search."""

    @abc.abstractmethod
    async def delete(self, entry_id: str) -> bool:
        """Delete a memory entry. Returns True if found and deleted."""

    async def count(self) -> int:
        """Count entries in this tier. Override for efficiency."""
        return 0

    async def health(self) -> str:
        """Return health status string."""
        return "ok" if self._ready else "not_initialized"
