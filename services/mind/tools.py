"""Tool registry and built-in tool implementations for MIND agents.

Ported from orchestrator/tools.py with improvements:
- Memory service integration (search, store)
- Better error handling
- Extensible registration API
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

import httpx

from local_system.config import Settings
from local_system.utils import generate_id

logger = logging.getLogger("mind.tools")

ToolFunc = Callable[..., Awaitable[Any]]


class ToolRegistry:
    """Registry of tools available to MIND agents."""

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient) -> None:
        self.settings = settings
        self._http = http_client
        self._tools: dict[str, ToolFunc] = {}
        self._definitions: dict[str, dict[str, Any]] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        self.register(
            "calculator",
            "Evaluate a mathematical expression.",
            {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
            self._calculator,
        )
        self.register(
            "memory_search",
            "Search the memory system for relevant past knowledge, events, and documents.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "top_k": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
            self._memory_search,
        )
        self.register(
            "memory_store",
            "Store information in the memory system for future retrieval.",
            {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "tier": {"type": "string", "enum": ["episodic", "procedural", "resource", "vault"], "default": "episodic"},
                    "source": {"type": "string", "default": ""},
                    "tags": {"type": "array", "items": {"type": "string"}, "default": []},
                },
                "required": ["content"],
            },
            self._memory_store,
        )
        self.register(
            "web_fetch",
            "Fetch the text content of a URL.",
            {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
            self._web_fetch,
        )

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        func: ToolFunc,
    ) -> None:
        self._tools[name] = func
        self._definitions[name] = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }

    def get_definitions(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        if names is None:
            return list(self._definitions.values())
        return [self._definitions[n] for n in names if n in self._definitions]

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        func = self._tools.get(name)
        if not func:
            raise ValueError(f"Unknown tool: {name}")
        try:
            return await func(**arguments)
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}")
            return f"Error executing {name}: {e}"

    # --- Built-in tool implementations ---

    async def _calculator(self, expression: str) -> str:
        allowed = set("0123456789+-*/().% ")
        if not all(c in allowed for c in expression):
            return "Error: expression contains invalid characters"
        try:
            result = eval(expression, {"__builtins__": {}})  # noqa: S307
            return str(result)
        except Exception as e:
            return f"Error: {e}"

    async def _memory_search(self, query: str, top_k: int = 5) -> list[dict]:
        memory_url = f"http://localhost:{self.settings.ports.memory}"
        try:
            resp = await self._http.post(
                f"{memory_url}/v1/memory/search",
                json={"query": query, "top_k": top_k},
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {"content": r["content"], "source": r.get("source", ""), "confidence": r.get("confidence", 0)}
                for r in data.get("results", [])
            ]
        except Exception as e:
            return [{"error": str(e)}]

    async def _memory_store(
        self, content: str, tier: str = "episodic", source: str = "", tags: list[str] | None = None
    ) -> dict:
        memory_url = f"http://localhost:{self.settings.ports.memory}"
        try:
            resp = await self._http.post(
                f"{memory_url}/v1/memory/store",
                json={
                    "id": generate_id("mem"),
                    "tier": tier,
                    "content": content,
                    "source": source or "mind-agent",
                    "tags": tags or [],
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    async def _web_fetch(self, url: str) -> str:
        try:
            resp = await self._http.get(url, timeout=30.0)
            resp.raise_for_status()
            return resp.text[:10000]
        except Exception as e:
            return f"Error fetching {url}: {e}"
