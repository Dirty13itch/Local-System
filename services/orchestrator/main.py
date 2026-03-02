"""Orchestrator Service — agent and task management.

Manages AI agents, executes tool-augmented workflows, and coordinates
multi-step tasks across the system.
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
    task = Task(
        id=task_id,
        agent_id=body.get("agent_id"),
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
    """Execute a task using the agent runner."""
    from datetime import datetime, timezone

    task.status = TaskStatus.RUNNING
    try:
        result = await app.state.agent_runner.run(
            description=task.description,
            agent_id=config.get("agent_id"),
            model=config.get("model", "llama3.1:8b"),
            tools=config.get("tools", []),
            max_iterations=config.get("max_iterations", 10),
        )
        task.result = result
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now(timezone.utc)
    except Exception as e:
        logger.error(f"Task {task.id} failed: {e}")
        task.error = str(e)
        task.status = TaskStatus.FAILED
        task.completed_at = datetime.now(timezone.utc)
