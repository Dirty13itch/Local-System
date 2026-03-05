"""Capability Router — routes requests to the right handler.

Classifies incoming requests and dispatches them:
  - Chat/reasoning → LLM with memory context
  - Search/RAG → Memory service
  - Code execution → sandbox (future)
  - Image generation → ComfyUI via gateway
  - Infrastructure → cluster management (future)
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from local_system.models import SpecialistType

logger = logging.getLogger("mind.router")


class Capability(str, Enum):
    CHAT = "chat"
    SEARCH = "search"
    CODE = "code"
    CREATIVE = "creative"
    INFRASTRUCTURE = "infrastructure"
    ANALYSIS = "analysis"


# Keywords that hint at the appropriate capability
_CAPABILITY_HINTS: dict[Capability, list[str]] = {
    Capability.SEARCH: [
        "search", "find", "look up", "what is", "who is", "when did",
        "tell me about", "information on", "recall", "remember",
    ],
    Capability.CODE: [
        "code", "program", "function", "class", "debug", "fix",
        "implement", "refactor", "test", "compile", "deploy",
        "python", "javascript", "typescript", "rust", "go",
    ],
    Capability.CREATIVE: [
        "write", "story", "poem", "narrative", "character",
        "worldbuild", "scene", "queens", "empire", "eobq",
        "generate image", "draw", "illustrate", "comfyui",
    ],
    Capability.INFRASTRUCTURE: [
        "server", "container", "docker", "gpu", "cluster",
        "deploy", "restart", "health check", "monitor",
        "foundry", "vault", "workshop", "dev node",
    ],
    Capability.ANALYSIS: [
        "analyze", "calculate", "compare", "statistics",
        "data", "chart", "graph", "trend", "metric",
    ],
}


class CapabilityRouter:
    """Routes requests to appropriate capabilities and models."""

    # Capability → recommended model mapping
    MODEL_MAP: dict[Capability, str] = {
        Capability.CHAT: "reasoning",
        Capability.SEARCH: "fast",
        Capability.CODE: "coding",
        Capability.CREATIVE: "reasoning",
        Capability.INFRASTRUCTURE: "fast",
        Capability.ANALYSIS: "reasoning",
    }

    # Capability → tools to make available
    TOOL_MAP: dict[Capability, list[str]] = {
        Capability.CHAT: ["memory_search", "calculator"],
        Capability.SEARCH: ["memory_search", "web_fetch"],
        Capability.CODE: ["memory_search", "memory_store"],
        Capability.CREATIVE: ["memory_search", "memory_store"],
        Capability.INFRASTRUCTURE: ["memory_search"],
        Capability.ANALYSIS: ["memory_search", "calculator"],
    }

    # Specialist type → capability
    SPECIALIST_MAP: dict[SpecialistType, Capability] = {
        SpecialistType.RESEARCH: Capability.SEARCH,
        SpecialistType.CODING: Capability.CODE,
        SpecialistType.CREATIVE: Capability.CREATIVE,
        SpecialistType.INFRASTRUCTURE: Capability.INFRASTRUCTURE,
        SpecialistType.GENERAL: Capability.CHAT,
    }

    def classify(
        self,
        text: str,
        specialist: SpecialistType | None = None,
    ) -> Capability:
        """Classify a request into a capability.

        Uses explicit specialist override first, then keyword heuristics.
        """
        # Explicit specialist mapping takes priority
        if specialist and specialist in self.SPECIALIST_MAP:
            cap = self.SPECIALIST_MAP[specialist]
            logger.debug(f"Routed via specialist {specialist.value} → {cap.value}")
            return cap

        # Keyword-based classification
        text_lower = text.lower()
        scores: dict[Capability, int] = {cap: 0 for cap in Capability}

        for cap, keywords in _CAPABILITY_HINTS.items():
            for kw in keywords:
                if kw in text_lower:
                    scores[cap] += 1

        best = max(scores, key=scores.get)
        if scores[best] > 0:
            logger.debug(f"Routed via keywords → {best.value} (score={scores[best]})")
            return best

        # Default to chat
        return Capability.CHAT

    def get_model(self, capability: Capability, override: str | None = None) -> str:
        """Get the recommended model for a capability."""
        return override or self.MODEL_MAP.get(capability, "reasoning")

    def get_tools(self, capability: Capability, override: list[str] | None = None) -> list[str]:
        """Get the recommended tools for a capability."""
        return override or self.TOOL_MAP.get(capability, ["memory_search"])

    def get_system_prompt(self, capability: Capability) -> str:
        """Get a capability-appropriate system prompt."""
        prompts = {
            Capability.CHAT: (
                "You are a helpful AI assistant. You have access to a memory system "
                "with information from past conversations and ingested documents. "
                "Use tools when they would help answer the user's question."
            ),
            Capability.SEARCH: (
                "You are a research assistant. Search memory and documents to find "
                "relevant information. Cite sources when possible. Be thorough."
            ),
            Capability.CODE: (
                "You are an expert programmer. Help write, debug, and explain code. "
                "Check memory for relevant past solutions and patterns."
            ),
            Capability.CREATIVE: (
                "You are a creative writing assistant specializing in worldbuilding, "
                "narrative, and character development. Check memory for established "
                "lore and continuity."
            ),
            Capability.INFRASTRUCTURE: (
                "You are a DevOps and infrastructure specialist. Help manage servers, "
                "containers, GPUs, and deployments across the cluster."
            ),
            Capability.ANALYSIS: (
                "You are a data analyst. Help calculate, analyze, and interpret data. "
                "Use the calculator tool for precise computations."
            ),
        }
        return prompts.get(capability, prompts[Capability.CHAT])
