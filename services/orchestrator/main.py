"""Orchestrator Service — agent lifecycle and task management.

Manages specialist agents, integrates with the cognitive workspace,
and coordinates multi-step tasks. Uses memory service for context.

Runs on VAULT.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException

from local_system.config import get_settings
from local_system.models import (
    AgentConfig,
    HealthResponse,
    SpecialistType,
    Task,
    TaskStatus,
)
from local_system.utils import generate_id, setup_logging

from agent import AgentRunner
from tools import ToolRegistry

settings = get_settings()
logger = setup_logging("orchestrator", settings)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Orchestrator starting")
    app.state.tool_registry = ToolRegistry(settings)
    app.state.agent_runner = AgentRunner(settings, app.state.tool_registry)
    app.state.tasks: dict[str, Task] = {}
    app.state.start_time = time.time()
    yield
    logger.info("Orchestrator stopped")


app = FastAPI(
    title="Local-System Orchestrator",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(
        service="orchestrator",
        node=settings.node.name.value,
        uptime_seconds=time.time() - app.state.start_time,
    )


@app.get("/v1/agents")
async def list_agents() -> list[AgentConfig]:
    """List available agent configurations."""
    return app.state.agent_runner.list_agents()


@app.post("/v1/tasks")
async def create_task(body: dict) -> Task:
    """Create and execute a new agent task."""
    task_id = generate_id("task")
    specialist = SpecialistType(body.get("specialist", "general"))

    task = Task(
        id=task_id,
        agent_id=body.get("agent_id"),
        specialist=specialist,
        description=body.get("description", ""),
    )
    app.state.tasks[task_id] = task

    # Run task asynchronously
    import asyncio

    asyncio.create_task(_run_task(task, body))

    return task


@app.get("/v1/tasks/{task_id}")
async def get_task(task_id: str) -> Task:
    task = app.state.tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.get("/v1/tasks")
async def list_tasks(status: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    tasks = list(app.state.tasks.values())
    if status:
        tasks = [t for t in tasks if t.status.value == status]
    return {
        "tasks": tasks[offset : offset + limit],
        "total": len(tasks),
    }


@app.post("/v1/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> Task:
    task = app.state.tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = TaskStatus.CANCELLED
    return task


async def _run_task(task: Task, config: dict) -> None:
    """Execute a task using the agent runner, with memory integration."""
    from datetime import datetime, timezone

    task.status = TaskStatus.RUNNING

    # Fetch relevant memory context
    memory_context: list[str] = []
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"http://localhost:{settings.ports.memory}/v1/memory/search",
                json={"query": task.description, "top_k": 5},
                timeout=10.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                memory_context = [r["content"] for r in data.get("results", [])]
                task.memory_context = [r.get("id", "") for r in data.get("results", [])]
    except Exception as e:
        logger.warning(f"Memory lookup failed for task {task.id}: {e}")

    try:
        result = await app.state.agent_runner.run(
            description=task.description,
            agent_id=config.get("agent_id"),
            model=config.get("model", "reasoning"),
            tools=config.get("tools", []),
            max_iterations=config.get("max_iterations", 10),
            memory_context=memory_context,
        )
        task.result = result
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now(timezone.utc)

        # Store episodic memory of task completion
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                await client.post(
                    f"http://localhost:{settings.ports.memory}/v1/memory/episodic",
                    json={
                        "id": generate_id("ep"),
                        "event_type": "task_outcome",
                        "summary": f"Task completed: {task.description[:100]}",
                        "details": {"task_id": task.id, "specialist": task.specialist.value},
                        "outcome": "success",
                    },
                    timeout=5.0,
                )
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Task {task.id} failed: {e}")
        task.error = str(e)
        task.status = TaskStatus.FAILED
        task.completed_at = datetime.now(timezone.utc)
