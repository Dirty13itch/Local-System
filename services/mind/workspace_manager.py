"""Workspace manager — context switching for MIND service.

Reads workspace definitions from PostgreSQL (pre-seeded),
caches active workspace per session in Redis, and provides
workspace-aware configuration to the reasoning engine.

Each workspace shapes: default model, persona, tools, memory tier priorities.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from local_system.config import get_settings

logger = logging.getLogger("mind.workspaces")

# Default tool sets per workspace type
WORKSPACE_TOOLS: dict[str, list[str]] = {
    "infrastructure": ["calculator", "memory_search", "memory_store", "web_fetch"],
    "app_dev": ["calculator", "memory_search", "memory_store", "web_fetch"],
    "game_dev": ["calculator", "memory_search", "memory_store", "web_fetch"],
    "data_science": ["calculator", "memory_search", "memory_store", "web_fetch"],
    "creative_studio": ["memory_search", "memory_store", "web_fetch"],
    "media_library": ["memory_search", "memory_store", "web_fetch"],
    "home_automation": ["calculator", "memory_search", "memory_store", "web_fetch"],
    "research": ["memory_search", "memory_store", "web_fetch"],
    "business_finance": ["calculator", "memory_search", "memory_store", "web_fetch"],
    "travel_lifestyle": ["memory_search", "memory_store", "web_fetch"],
}

# Memory tier priorities per workspace type
WORKSPACE_MEMORY_TIERS: dict[str, list[str]] = {
    "infrastructure": ["procedural", "vault", "episodic", "resource"],
    "app_dev": ["procedural", "resource", "episodic", "vault"],
    "game_dev": ["procedural", "resource", "episodic"],
    "data_science": ["resource", "procedural", "vault", "episodic"],
    "creative_studio": ["episodic", "resource"],
    "media_library": ["resource", "episodic"],
    "home_automation": ["procedural", "vault", "episodic"],
    "research": ["resource", "vault", "semantic", "episodic"],
    "business_finance": ["vault", "procedural", "resource"],
    "travel_lifestyle": ["episodic", "resource"],
}


@dataclass
class WorkspaceConfig:
    """Active workspace configuration."""

    id: str
    slug: str
    name: str
    workspace_type: str
    description: str = ""
    icon: str = ""
    default_model: str = "reasoning"
    persona: str = ""
    tools: list[str] = field(default_factory=list)
    memory_tiers: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)

    def to_system_prompt_fragment(self) -> str:
        """Generate a system prompt fragment for this workspace."""
        parts = [f"Active workspace: {self.name} ({self.workspace_type})"]
        if self.description:
            parts.append(f"Context: {self.description}")
        if self.persona:
            parts.append(f"Persona: {self.persona}")
        return "\n".join(parts)


class WorkspaceManager:
    """Manages workspace definitions and active workspace per session."""

    def __init__(self) -> None:
        self._pool = None
        self._redis = None
        self._settings = get_settings()
        self._cache: dict[str, WorkspaceConfig] = {}
        self._default_workspace: WorkspaceConfig | None = None

    async def init(self, db_pool=None, redis_client=None) -> None:
        """Initialize with shared DB pool and Redis client."""
        self._pool = db_pool
        self._redis = redis_client

        # Load all workspaces into cache
        if self._pool:
            try:
                async with self._pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT * FROM workspaces ORDER BY name"
                    )
                    for row in rows:
                        ws = self._row_to_config(row)
                        self._cache[ws.slug] = ws
                        if ws.slug == "infrastructure":
                            self._default_workspace = ws

                logger.info(f"Loaded {len(self._cache)} workspaces from DB")
            except Exception as e:
                logger.warning(f"Failed to load workspaces: {e}")

        if not self._default_workspace and self._cache:
            self._default_workspace = next(iter(self._cache.values()))

    def list_workspaces(self) -> list[dict[str, Any]]:
        """List all available workspaces."""
        return [
            {
                "slug": ws.slug,
                "name": ws.name,
                "type": ws.workspace_type,
                "icon": ws.icon,
                "default_model": ws.default_model,
                "description": ws.description,
            }
            for ws in self._cache.values()
        ]

    def get_workspace(self, slug: str) -> WorkspaceConfig | None:
        """Get workspace config by slug."""
        return self._cache.get(slug)

    async def get_active_workspace(self, session_id: str) -> WorkspaceConfig:
        """Get the active workspace for a session."""
        if self._redis:
            try:
                slug = await self._redis.get(f"ls:workspace:{session_id}")
                if slug and slug in self._cache:
                    return self._cache[slug]
            except Exception:
                pass
        return self._default_workspace or WorkspaceConfig(
            id="default", slug="default", name="Default",
            workspace_type="general", default_model="reasoning",
        )

    async def set_active_workspace(
        self, session_id: str, slug: str
    ) -> WorkspaceConfig | None:
        """Switch the active workspace for a session."""
        ws = self._cache.get(slug)
        if not ws:
            return None

        if self._redis:
            try:
                await self._redis.set(
                    f"ls:workspace:{session_id}", slug, ex=86400  # 24h TTL
                )
            except Exception as e:
                logger.warning(f"Failed to store workspace preference: {e}")

        logger.info(f"Session {session_id[:12]} switched to workspace: {ws.name}")
        return ws

    def _row_to_config(self, row) -> WorkspaceConfig:
        """Convert a DB row to WorkspaceConfig."""
        ws_type = row["workspace_type"]
        config_json = row.get("config") or {}
        if isinstance(config_json, str):
            config_json = json.loads(config_json)

        return WorkspaceConfig(
            id=str(row["id"]),
            slug=row["slug"],
            name=row["name"],
            workspace_type=ws_type,
            description=row.get("description", ""),
            icon=row.get("icon", ""),
            default_model=row.get("default_model", "reasoning"),
            persona=row.get("persona", ""),
            tools=WORKSPACE_TOOLS.get(ws_type, ["memory_search", "memory_store"]),
            memory_tiers=WORKSPACE_MEMORY_TIERS.get(ws_type, ["episodic", "vault"]),
            config=config_json,
        )
