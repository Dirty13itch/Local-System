"""Core reasoning loop — the brain of the MIND service.

8-step loop: Contextualize → Route → Assemble → Think → Act → Observe → Respond → Remember

Handles:
- Single-turn chat completions
- Multi-turn conversations with history
- Tool-augmented agent workflows
- Memory-integrated context enrichment
- Workspace-aware model/tool/persona selection
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

import httpx

from local_system.config import get_settings
from local_system.models import AgentConfig, SpecialistType
from local_system.utils import generate_id

from .db import MindDB
from .events import EventBus
from .router import Capability, CapabilityRouter
from .tools import ToolRegistry

if TYPE_CHECKING:
    from .workspace_manager import WorkspaceConfig

logger = logging.getLogger("mind.reasoning")

settings = get_settings()

# Default agent presets
DEFAULT_AGENTS: list[AgentConfig] = [
    AgentConfig(
        name="general",
        system_prompt="You are a helpful AI assistant with access to tools and memory.",
        model="reasoning",
        tools=["memory_search", "calculator", "web_fetch"],
        max_iterations=10,
    ),
    AgentConfig(
        name="coder",
        system_prompt="You are an expert programmer. Help write, debug, and explain code.",
        model="coding",
        tools=["memory_search", "memory_store"],
        max_iterations=15,
    ),
    AgentConfig(
        name="researcher",
        system_prompt="You are a research assistant. Search memory and the web thoroughly.",
        model="reasoning",
        tools=["memory_search", "web_fetch"],
        max_iterations=20,
    ),
    AgentConfig(
        name="creative",
        system_prompt=(
            "You are a creative writing assistant specializing in worldbuilding "
            "and narrative for the Empire of Broken Queens universe."
        ),
        model="reasoning",
        tools=["memory_search", "memory_store"],
        max_iterations=15,
    ),
    AgentConfig(
        name="fast",
        system_prompt="You are a fast, concise assistant for quick tasks.",
        model="fast",
        tools=["calculator"],
        max_iterations=5,
    ),
]


class ReasoningEngine:
    """Central reasoning engine with memory-augmented LLM workflows."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        router: CapabilityRouter,
        db: MindDB,
        events: EventBus,
        http_client: httpx.AsyncClient,
    ) -> None:
        self.tools = tool_registry
        self.router = router
        self.db = db
        self.events = events
        self._http = http_client
        self.agents = {a.name: a for a in DEFAULT_AGENTS}
        self._inference_url = settings.inference.litellm_host.rstrip("/")
        self._api_key = settings.inference.litellm_key

    def list_agents(self) -> list[AgentConfig]:
        return list(self.agents.values())

    async def process(
        self,
        message: str,
        *,
        conversation_id: str | None = None,
        model: str | None = None,
        specialist: str | None = None,
        agent_id: str | None = None,
        tools: list[str] | None = None,
        max_iterations: int | None = None,
        stream: bool = False,
        workspace: WorkspaceConfig | None = None,
    ) -> dict[str, Any]:
        """Process a message through the full reasoning loop.

        Args:
            workspace: Optional workspace config that shapes model, tools,
                       persona, and memory tier priorities.

        Returns:
            Dict with keys: response, conversation_id, model, capability,
            tool_calls, tokens, latency_ms, workspace
        """
        start = time.time()

        # 1. CONTEXTUALIZE — resolve conversation, load history
        conv_id = conversation_id or generate_id("conv")
        ws_slug = workspace.slug if workspace else "default"
        if self.db.ready:
            await self.db.create_conversation(conv_id, workspace=ws_slug, model=model or "reasoning")

        history = []
        if conversation_id and self.db.ready:
            rows = await self.db.get_messages(conversation_id, limit=50)
            history = [{"role": r["role"], "content": r["content"]} for r in rows]

        # 2. ROUTE — classify capability, pick model and tools
        spec = SpecialistType(specialist) if specialist else None
        capability = self.router.classify(message, specialist=spec)

        # Workspace overrides (lowest priority — explicit params win)
        resolved_model = model
        resolved_tools = tools

        if workspace and not resolved_model:
            resolved_model = workspace.default_model
        if workspace and not resolved_tools:
            resolved_tools = workspace.tools

        # Capability-based defaults (if workspace didn't set them)
        if not resolved_model:
            resolved_model = self.router.get_model(capability)
        if not resolved_tools:
            resolved_tools = self.router.get_tools(capability)

        # Agent preset overrides
        if agent_id and agent_id in self.agents:
            agent = self.agents[agent_id]
            if not model:
                resolved_model = agent.model
            if not tools:
                resolved_tools = agent.tools
            max_iterations = max_iterations or agent.max_iterations

        max_iter = max_iterations or 10

        # 3. ASSEMBLE — build prompt with memory context + workspace persona
        memory_context = await self._fetch_memory_context(message)

        system_prompt = self.router.get_system_prompt(capability)
        if agent_id and agent_id in self.agents:
            system_prompt = self.agents[agent_id].system_prompt

        # Inject workspace context into system prompt
        if workspace:
            ws_fragment = workspace.to_system_prompt_fragment()
            system_prompt = f"{ws_fragment}\n\n{system_prompt}"

        if memory_context:
            ctx_block = "\n".join(f"- {c}" for c in memory_context)
            system_prompt += (
                f"\n\n## Relevant Memory Context\n"
                f"The following was retrieved from memory:\n{ctx_block}"
            )

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": message})

        # Store user message
        if self.db.ready:
            await self.db.store_message(
                generate_id("msg"), conv_id, "user", message
            )

        # 4-6. THINK -> ACT -> OBSERVE (agent loop)
        tool_defs = self.tools.get_definitions(resolved_tools) if resolved_tools else None
        all_tool_calls: list[dict] = []
        total_tokens_in = 0
        total_tokens_out = 0

        response_content = ""
        for iteration in range(max_iter):
            iter_start = time.time()

            payload: dict[str, Any] = {
                "model": resolved_model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 4096,
                "stream": False,
            }
            if tool_defs:
                payload["tools"] = tool_defs

            try:
                resp = await self._http.post(
                    f"{self._inference_url}/v1/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=120.0,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"LLM call failed (iter {iteration}): {e}")
                response_content = f"Error: LLM call failed — {e}"
                break

            choice = data.get("choices", [{}])[0]
            assistant_msg = choice.get("message", {})
            usage = data.get("usage", {})
            total_tokens_in += usage.get("prompt_tokens", 0)
            total_tokens_out += usage.get("completion_tokens", 0)

            messages.append(assistant_msg)

            # Log iteration
            iter_ms = int((time.time() - iter_start) * 1000)
            if self.db.ready and conversation_id:
                await self.db.log_agent_action(
                    conv_id, iteration, "llm_call",
                    {"model": resolved_model, "tokens": usage},
                    duration_ms=iter_ms,
                )

            # Check for tool calls
            tool_calls = assistant_msg.get("tool_calls", [])
            if not tool_calls:
                response_content = assistant_msg.get("content", "")
                break

            # Execute tool calls
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                try:
                    tool_args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    tool_args = {}

                logger.info(f"Executing tool: {tool_name} (iter {iteration})")
                tool_start = time.time()
                result = await self.tools.execute(tool_name, tool_args)
                tool_ms = int((time.time() - tool_start) * 1000)

                result_str = json.dumps(result) if not isinstance(result, str) else result
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_str,
                })

                all_tool_calls.append({
                    "tool": tool_name,
                    "args": tool_args,
                    "result_preview": result_str[:200],
                    "duration_ms": tool_ms,
                })

                if self.db.ready:
                    await self.db.log_agent_action(
                        conv_id, iteration, "tool_exec",
                        {"tool": tool_name, "args": tool_args},
                        duration_ms=tool_ms,
                    )
        else:
            # Max iterations reached
            response_content = messages[-1].get("content", "Max iterations reached.")

        # 7. RESPOND — store and return
        total_ms = int((time.time() - start) * 1000)

        if self.db.ready:
            await self.db.store_message(
                generate_id("msg"), conv_id, "assistant", response_content,
                model=resolved_model,
                tokens_in=total_tokens_in,
                tokens_out=total_tokens_out,
                latency_ms=total_ms,
            )

        # 8. REMEMBER — publish event for memory pipeline
        if self.events.ready:
            await self.events.publish(
                "mind.response",
                "reasoning_complete",
                {
                    "conversation_id": conv_id,
                    "capability": capability.value,
                    "model": resolved_model,
                    "workspace": ws_slug,
                    "tokens_in": total_tokens_in,
                    "tokens_out": total_tokens_out,
                    "latency_ms": total_ms,
                    "tool_calls": len(all_tool_calls),
                },
            )

        return {
            "response": response_content,
            "conversation_id": conv_id,
            "model": resolved_model,
            "capability": capability.value,
            "workspace": ws_slug,
            "tool_calls": all_tool_calls,
            "tokens": {"in": total_tokens_in, "out": total_tokens_out},
            "latency_ms": total_ms,
        }

    async def _fetch_memory_context(self, query: str) -> list[str]:
        """Fetch relevant context from the memory service."""
        try:
            resp = await self._http.post(
                f"http://localhost:{settings.ports.memory}/v1/memory/search",
                json={"query": query, "top_k": 5},
                timeout=10.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                return [r["content"] for r in data.get("results", [])[:5]]
        except Exception as e:
            logger.debug(f"Memory context fetch failed: {e}")
        return []
