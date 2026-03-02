"""Agent execution engine — runs tool-augmented LLM workflows."""

from __future__ import annotations

import json
from typing import Any

import httpx

from local_system.config import Settings
from local_system.models import AgentConfig, AgentState, Message, Role
from local_system.utils import generate_id, setup_logging

from tools import ToolRegistry

logger = setup_logging("orchestrator.agent")

# Built-in agent presets
DEFAULT_AGENTS: list[AgentConfig] = [
    AgentConfig(
        name="general",
        system_prompt="You are a helpful AI assistant with access to tools. Use them to help the user.",
        model="llama3.1:8b",
        tools=["search", "calculator", "web_fetch"],
        max_iterations=10,
    ),
    AgentConfig(
        name="coder",
        system_prompt="You are an expert programmer. Help the user write, debug, and explain code.",
        model="codellama:34b",
        tools=["search", "file_read", "file_write", "shell"],
        max_iterations=15,
    ),
    AgentConfig(
        name="researcher",
        system_prompt="You are a research assistant. Search documents and the web to answer questions thoroughly.",
        model="llama3.1:70b",
        tools=["search", "web_fetch", "rag_search"],
        max_iterations=20,
    ),
]


class AgentRunner:
    """Executes agent tasks with tool-use loops."""

    def __init__(self, settings: Settings, tool_registry: ToolRegistry) -> None:
        self.settings = settings
        self.tool_registry = tool_registry
        self.agents = {a.name: a for a in DEFAULT_AGENTS}
        self._inference_url = (
            f"http://{settings.network.node1_host}:{settings.ports.inference}"
        )

    def list_agents(self) -> list[AgentConfig]:
        return list(self.agents.values())

    async def run(
        self,
        description: str,
        agent_id: str | None = None,
        model: str | None = None,
        tools: list[str] | None = None,
        max_iterations: int = 10,
    ) -> Any:
        """Run an agent task to completion."""
        # Resolve agent config
        agent = self.agents.get(agent_id or "general", DEFAULT_AGENTS[0])
        model = model or agent.model
        tool_names = tools or agent.tools
        max_iter = max_iterations or agent.max_iterations

        # Build tool definitions for the LLM
        tool_defs = self.tool_registry.get_definitions(tool_names)

        # Initialize conversation
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": agent.system_prompt},
            {"role": "user", "content": description},
        ]

        # Agent loop
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            for iteration in range(max_iter):
                logger.info(f"Agent iteration {iteration + 1}/{max_iter}")

                # Call the LLM
                payload = {
                    "model": model,
                    "messages": messages,
                    "tools": tool_defs,
                    "temperature": agent.temperature,
                    "max_tokens": 4096,
                    "stream": False,
                }

                resp = await client.post(
                    f"{self._inference_url}/v1/chat/completions",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

                assistant_msg = data.get("message", {})
                messages.append({"role": "assistant", **assistant_msg})

                # Check for tool calls
                tool_calls = assistant_msg.get("tool_calls", [])
                if not tool_calls:
                    # No tool calls — agent is done
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
