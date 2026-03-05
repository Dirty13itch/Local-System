"""Agent execution engine — runs tool-augmented LLM workflows.

Routes all inference through LiteLLM on VAULT:4000, which handles
model alias routing (reasoning/coding/fast) to vLLM on FOUNDRY/WORKSHOP.
Injects memory context from the memory service into agent prompts.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from local_system.config import Settings
from local_system.models import AgentConfig, SpecialistType
from local_system.utils import setup_logging

from tools import ToolRegistry

logger = setup_logging("orchestrator.agent")

# Agent presets aligned with specialist types and the proven inference stack.
# All models are LiteLLM virtual names — routing is handled by LiteLLM config.
DEFAULT_AGENTS: list[AgentConfig] = [
    AgentConfig(
        name="general",
        system_prompt="You are a helpful AI assistant with access to tools. Use them to help the user.",
        model="reasoning",
        tools=["search", "calculator", "web_fetch"],
        max_iterations=10,
    ),
    AgentConfig(
        name="coder",
        system_prompt=(
            "You are an expert programmer. Help the user write, debug, and explain code. "
            "You have access to file operations and a shell."
        ),
        model="reasoning",
        tools=["search", "file_read", "file_write", "shell"],
        max_iterations=15,
    ),
    AgentConfig(
        name="researcher",
        system_prompt=(
            "You are a research assistant. Search documents and the web to answer "
            "questions thoroughly. Cite sources when possible."
        ),
        model="reasoning",
        tools=["search", "web_fetch", "rag_search"],
        max_iterations=20,
    ),
    AgentConfig(
        name="creative",
        system_prompt=(
            "You are a creative writing assistant specializing in worldbuilding, "
            "narrative, and character development for the Empire of Broken Queens universe."
        ),
        model="reasoning",
        tools=["search", "rag_search", "file_read", "file_write"],
        max_iterations=15,
    ),
    AgentConfig(
        name="building_science",
        system_prompt=(
            "You are a building science and HERS rating specialist. Help with energy "
            "modeling, code compliance, and building performance analysis."
        ),
        model="reasoning",
        tools=["search", "rag_search", "calculator"],
        max_iterations=15,
    ),
    AgentConfig(
        name="fast",
        system_prompt="You are a fast, concise assistant for quick tasks.",
        model="fast",
        tools=["search", "calculator"],
        max_iterations=5,
    ),
]


class AgentRunner:
    """Executes agent tasks with tool-use loops.

    All inference routes through LiteLLM on VAULT:4000, which handles
    model alias routing to vLLM backends on FOUNDRY and WORKSHOP.
    """

    def __init__(self, settings: Settings, tool_registry: ToolRegistry) -> None:
        self.settings = settings
        self.tool_registry = tool_registry
        self.agents = {a.name: a for a in DEFAULT_AGENTS}
        # LiteLLM is the single entry point for all inference
        self._inference_url = settings.inference.litellm_host.rstrip("/")
        self._api_key = settings.inference.litellm_key

    def list_agents(self) -> list[AgentConfig]:
        return list(self.agents.values())

    async def run(
        self,
        description: str,
        agent_id: str | None = None,
        model: str | None = None,
        tools: list[str] | None = None,
        max_iterations: int = 10,
        memory_context: list[str] | None = None,
    ) -> Any:
        """Run an agent task to completion.

        Args:
            description: The task to accomplish.
            agent_id: Which agent preset to use.
            model: Override model (LiteLLM virtual name).
            tools: Override tool list.
            max_iterations: Max tool-use iterations.
            memory_context: Relevant memory snippets from the memory service.
        """
        # Resolve agent config
        agent = self.agents.get(agent_id or "general", DEFAULT_AGENTS[0])
        model = model or agent.model
        tool_names = tools or agent.tools
        max_iter = max_iterations or agent.max_iterations

        # Build tool definitions for the LLM
        tool_defs = self.tool_registry.get_definitions(tool_names)

        # Build system prompt with memory context
        system_prompt = agent.system_prompt
        if memory_context:
            context_block = "\n".join(f"- {ctx}" for ctx in memory_context)
            system_prompt += (
                f"\n\n## Relevant Memory Context\n"
                f"The following information was retrieved from memory and may be relevant:\n"
                f"{context_block}"
            )

        # Initialize conversation
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": description},
        ]

        # Agent loop — route through LiteLLM
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            for iteration in range(max_iter):
                logger.info(f"Agent iteration {iteration + 1}/{max_iter}")

                payload = {
                    "model": model,
                    "messages": messages,
                    "tools": tool_defs if tool_defs else None,
                    "temperature": agent.temperature,
                    "max_tokens": 4096,
                    "stream": False,
                }

                resp = await client.post(
                    f"{self._inference_url}/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

                assistant_msg = data.get("message", {})
                messages.append({"role": "assistant", **assistant_msg})

                # Check for tool calls
                tool_calls = assistant_msg.get("tool_calls", [])
                if not tool_calls:
                    return assistant_msg.get("content", "")

                # Execute tool calls
                for tc in tool_calls:
                    tool_name = tc["name"]
                    tool_args = tc.get("arguments", {})
                    logger.info(f"Executing tool: {tool_name}")

                    try:
                        result = await self.tool_registry.execute(tool_name, tool_args)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps(result) if not isinstance(result, str) else result,
                        })
                    except Exception as e:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": f"Error: {e}",
                        })

        return messages[-1].get("content", "Max iterations reached")
