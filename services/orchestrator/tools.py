"""Tool registry and built-in tool implementations."""

from __future__ import annotations

from typing import Any, Callable, Awaitable

import httpx

from local_system.config import Settings
from local_system.utils import setup_logging

logger = setup_logging("orchestrator.tools")

ToolFunc = Callable[..., Awaitable[Any]]


class ToolRegistry:
    """Registry of tools available to agents."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._tools: dict[str, ToolFunc] = {}
        self._definitions: dict[str, dict[str, Any]] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        """Register built-in tools."""
        self.register(
            "calculator",
            "Evaluate a mathematical expression.",
            {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
            self._calculator,
        )
        self.register(
            "rag_search",
            "Search the local document knowledge base.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "collection": {"type": "string", "default": "default"},
                    "top_k": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
            self._rag_search,
        )
        self.register(
            "web_fetch",
            "Fetch the content of a URL.",
            {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
            self._web_fetch,
        )
        self.register(
            "search",
            "Search the web for information.",
            {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            self._search,
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
            "name": name,
            "description": description,
            "parameters": parameters,
        }

    def get_definitions(self, names: list[str]) -> list[dict[str, Any]]:
        return [self._definitions[n] for n in names if n in self._definitions]

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        func = self._tools.get(name)
        if not func:
            raise ValueError(f"Unknown tool: {name}")
        return await func(**arguments)

    # --- Built-in tool implementations ---

    async def _calculator(self, expression: str) -> str:
        """Safely evaluate a math expression."""
        # Only allow safe math operations
        allowed = set("0123456789+-*/().% ")
        if not all(c in allowed for c in expression):
            return "Error: expression contains invalid characters"
        try:
            result = eval(expression, {"__builtins__": {}})  # noqa: S307
            return str(result)
        except Exception as e:
            return f"Error: {e}"

    async def _rag_search(
        self, query: str, collection: str = "default", top_k: int = 5
    ) -> list[dict]:
        rag_url = f"http://{self.settings.network.vault}:8704"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{rag_url}/v1/search",
                json={"query": query, "collection": collection, "top_k": top_k},
            )
            resp.raise_for_status()
            return resp.json().get("results", [])

    async def _web_fetch(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            # Return first 10K chars of text content
            return resp.text[:10000]

    async def _search(self, query: str) -> str:
        # Placeholder — integrate with a search API or local search engine
        return f"Search results for '{query}' — not yet implemented. Connect a search provider."
