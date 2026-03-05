"""Canonical workspace definitions for Local-System.

Workspace definitions are shared across services (MIND, MCP servers, Gateway).
The WorkspaceManager in services/mind/ uses these at runtime; this module
provides the static definitions and type helpers.

Each workspace configures:
- Default model alias (from LiteLLM)
- Available tools
- Memory tier priorities (which tiers to search first)
- Persona hint for the reasoning engine
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WorkspaceType(str, Enum):
    """All supported workspace types."""
    APP_DEV = "app_dev"
    GAME_DEV = "game_dev"
    DATA_SCIENCE = "data_science"
    CREATIVE_STUDIO = "creative_studio"
    MEDIA_LIBRARY = "media_library"
    INFRASTRUCTURE = "infrastructure"
    HOME_AUTOMATION = "home_automation"
    RESEARCH = "research"
    BUSINESS_FINANCE = "business_finance"
    TRAVEL_LIFESTYLE = "travel_lifestyle"


@dataclass(frozen=True)
class WorkspaceDefinition:
    """Static workspace definition (shared across services)."""
    slug: str
    name: str
    workspace_type: WorkspaceType
    description: str
    icon: str = ""
    default_model: str = "reasoning"
    persona: str = ""
    tools: tuple[str, ...] = ("memory_search", "memory_store")
    memory_tiers: tuple[str, ...] = ("episodic", "vault")


# ─── Canonical workspace definitions ─────────────────────────────────

CORE_TOOLS = ("calculator", "memory_search", "memory_store", "web_fetch")
SEARCH_TOOLS = ("memory_search", "memory_store", "web_fetch")

WORKSPACES: dict[str, WorkspaceDefinition] = {
    "infrastructure": WorkspaceDefinition(
        slug="infrastructure",
        name="Infrastructure Ops",
        workspace_type=WorkspaceType.INFRASTRUCTURE,
        description="Cluster management, Docker, networking, monitoring",
        icon="S",
        default_model="reasoning",
        persona="Infrastructure expert. Precise, careful with destructive ops.",
        tools=CORE_TOOLS,
        memory_tiers=("procedural", "vault", "episodic", "resource"),
    ),
    "app-dev": WorkspaceDefinition(
        slug="app-dev",
        name="Application Development",
        workspace_type=WorkspaceType.APP_DEV,
        description="Building software -- web apps, APIs, CLI tools",
        icon="D",
        default_model="coding",
        persona="Senior full-stack developer. Clean code, pragmatic architecture.",
        tools=CORE_TOOLS,
        memory_tiers=("procedural", "resource", "episodic", "vault"),
    ),
    "game-dev": WorkspaceDefinition(
        slug="game-dev",
        name="Game Development",
        workspace_type=WorkspaceType.GAME_DEV,
        description="Game design, engines, mechanics, asset pipelines",
        icon="G",
        default_model="coding",
        persona="Game developer experienced in multiple engines and genres.",
        tools=CORE_TOOLS,
        memory_tiers=("procedural", "resource", "episodic"),
    ),
    "data-science": WorkspaceDefinition(
        slug="data-science",
        name="Data Science / ML",
        workspace_type=WorkspaceType.DATA_SCIENCE,
        description="Data analysis, ML training, notebooks, visualization",
        icon="M",
        default_model="reasoning",
        persona="Data scientist. Rigorous methodology, clear visualizations.",
        tools=CORE_TOOLS,
        memory_tiers=("resource", "procedural", "vault", "episodic"),
    ),
    "creative-studio": WorkspaceDefinition(
        slug="creative-studio",
        name="Creative Studio",
        workspace_type=WorkspaceType.CREATIVE_STUDIO,
        description="Image generation, video, voice synthesis, music creation",
        icon="P",
        default_model="creative",
        persona="Creative collaborator. Bold ideas, iterative refinement.",
        tools=SEARCH_TOOLS,
        memory_tiers=("episodic", "resource"),
    ),
    "media-library": WorkspaceDefinition(
        slug="media-library",
        name="Media Library",
        workspace_type=WorkspaceType.MEDIA_LIBRARY,
        description="Adult content management, performer database, TOSI scoring",
        icon="L",
        default_model="creative",
        persona="Media curator. Organized, detail-oriented, no judgment.",
        tools=SEARCH_TOOLS,
        memory_tiers=("resource", "episodic"),
    ),
    "home-automation": WorkspaceDefinition(
        slug="home-automation",
        name="Home Automation",
        workspace_type=WorkspaceType.HOME_AUTOMATION,
        description="Smart home, IoT, Home Assistant, energy management",
        icon="H",
        default_model="reasoning",
        persona="Home automation specialist. Safety-first, reliable integrations.",
        tools=CORE_TOOLS,
        memory_tiers=("procedural", "vault", "episodic"),
    ),
    "research": WorkspaceDefinition(
        slug="research",
        name="Research",
        workspace_type=WorkspaceType.RESEARCH,
        description="Deep research, literature review, synthesis, writing",
        icon="R",
        default_model="reasoning",
        persona="Research assistant. Thorough, well-sourced, critical analysis.",
        tools=SEARCH_TOOLS,
        memory_tiers=("resource", "vault", "semantic", "episodic"),
    ),
    "business-finance": WorkspaceDefinition(
        slug="business-finance",
        name="Business & Personal Finance",
        workspace_type=WorkspaceType.BUSINESS_FINANCE,
        description="Business operations, personal finance, tax, investments",
        icon="F",
        default_model="reasoning",
        persona="Financial analyst. Conservative advice, data-driven decisions.",
        tools=CORE_TOOLS,
        memory_tiers=("vault", "procedural", "resource"),
    ),
    "travel-lifestyle": WorkspaceDefinition(
        slug="travel-lifestyle",
        name="Travel & Lifestyle",
        workspace_type=WorkspaceType.TRAVEL_LIFESTYLE,
        description="Travel planning, lifestyle optimization, experiences",
        icon="T",
        default_model="fast",
        persona="Travel concierge. Creative itineraries, local expertise.",
        tools=SEARCH_TOOLS,
        memory_tiers=("episodic", "resource"),
    ),
}


def get_workspace(slug: str) -> WorkspaceDefinition | None:
    """Get a workspace definition by slug."""
    return WORKSPACES.get(slug)


def list_workspace_slugs() -> list[str]:
    """Get all workspace slugs."""
    return list(WORKSPACES.keys())


def get_tools_for_workspace(slug: str) -> tuple[str, ...]:
    """Get tool list for a workspace."""
    ws = WORKSPACES.get(slug)
    return ws.tools if ws else SEARCH_TOOLS


def get_memory_tiers_for_workspace(slug: str) -> tuple[str, ...]:
    """Get memory tier priorities for a workspace."""
    ws = WORKSPACES.get(slug)
    return ws.memory_tiers if ws else ("episodic", "vault")
