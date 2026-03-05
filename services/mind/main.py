"""MIND Service — Central reasoning engine for Local-System.

The brain of the system. Provides:
  - Chat/reasoning with memory-augmented context
  - Agent workflows with tool use
  - Capability routing (chat, code, search, creative, infra)
  - Conversation persistence
  - Event-driven architecture via Redis Streams
  - Task lifecycle management

Runs on DEV (:8710). All inference routed through LiteLLM on VAULT:4000.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException

from local_system.config import get_settings
from local_system.models import (
    AgentConfig,
    ChatRequest,
    HealthResponse,
    SpecialistType,
    Task,
    TaskStatus,
)
from local_system.utils import generate_id, setup_logging

from .db import MindDB
from .events import EventBus
from .reasoning import ReasoningEngine
from .router import CapabilityRouter
from .tools import ToolRegistry

settings = get_settings()
logger = setup_logging("mind", settings)

# --- Service components ---
_db = MindDB()
_events = EventBus()
_router = CapabilityRouter()
_tools: ToolRegistry | None = None
_engine: ReasoningEngine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _tools, _engine

    logger.info("MIND service starting")
    app.state.start_time = time.time()
    app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))

    # Initialize components
    await _db.init()
    await _events.init()

    _tools = ToolRegistry(settings, app.state.http_client)
    _engine = ReasoningEngine(
        tool_registry=_tools,
        router=_router,
        db=_db,
        events=_events,
        http_client=app.state.http_client,
    )

    status = {
        "db": _db.ready,
        "events": _events.ready,
        "tools": len(_tools.list_tools()),
        "agents": len(_engine.list_agents()),
    }
    logger.info(f"MIND service ready: {status}")

    yield

    # Shutdown
    await _db.close()
    await _events.close()
    await app.state.http_client.aclose()
    logger.info("MIND service stopped")


app = FastAPI(
    title="Local-System MIND",
    version="0.1.0",
    lifespan=lifespan,
)


# =============================================================================
# Health
# =============================================================================


@app.get("/health")
async def health() -> dict:
    return {
        **HealthResponse(
            service="mind",
            version="0.1.0",
            node=settings.node.name.value,
            uptime_seconds=time.time() - app.state.start_time,
        ).model_dump(),
        "components": {
            "db": _db.ready,
            "events": _events.ready,
            "tools": _tools.list_tools() if _tools else [],
            "agents": [a.name for a in _engine.list_agents()] if _engine else [],
        },
    }


# =============================================================================
# Chat / Reasoning
# =============================================================================


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest) -> dict:
    """OpenAI-compatible chat completion with memory augmentation.

    Processes messages through the reasoning loop:
    Contextualize → Route → Assemble → Think → Act → Observe → Respond → Remember
    """
    if not _engine:
        raise HTTPException(status_code=503, detail="Reasoning engine not initialized")

    # Extract the last user message
    user_message = ""
    for msg in reversed(req.messages):
        if msg.role == "user":
            user_message = msg.content
            break

    if not user_message:
        raise HTTPException(status_code=400, detail="No user message found")

    result = await _engine.process(
        message=user_message,
        conversation_id=req.conversation_id,
        model=req.model,
        stream=req.stream,
    )

    # Return in OpenAI-compatible format
    return {
        "id": generate_id("chatcmpl"),
        "object": "chat.completion",
        "model": result["model"],
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": result["response"],
            },
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": result["tokens"]["in"],
            "completion_tokens": result["tokens"]["out"],
            "total_tokens": result["tokens"]["in"] + result["tokens"]["out"],
        },
        "conversation_id": result["conversation_id"],
        "capability": result["capability"],
        "latency_ms": result["latency_ms"],
    }


@app.post("/v1/mind/process")
async def process_message(body: dict) -> dict:
    """Process a message through the MIND reasoning loop.

    More flexible than chat/completions — supports specialist routing,
    agent selection, and tool overrides.
    """
    if not _engine:
        raise HTTPException(status_code=503, detail="Reasoning engine not initialized")

    message = body.get("message", "")
    if not message:
        raise HTTPException(status_code=400, detail="'message' is required")

    return await _engine.process(
        message=message,
        conversation_id=body.get("conversation_id"),
        model=body.get("model"),
        specialist=body.get("specialist"),
        agent_id=body.get("agent_id"),
        tools=body.get("tools"),
        max_iterations=body.get("max_iterations"),
    )


# =============================================================================
# Agents
# =============================================================================


@app.get("/v1/agents")
async def list_agents() -> list[AgentConfig]:
    if not _engine:
        return []
    return _engine.list_agents()


# =============================================================================
# Tasks
# =============================================================================


@app.post("/v1/tasks")
async def create_task(body: dict) -> dict:
    """Create and execute an agent task."""
    if not _engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    task_id = generate_id("task")
    specialist = body.get("specialist", "general")
    description = body.get("description", "")

    if not description:
        raise HTTPException(status_code=400, detail="'description' is required")

    # Store task
    task_data = {
        "id": task_id,
        "specialist": specialist,
        "description": description,
        "status": "pending",
        "agent_id": body.get("agent_id"),
        "model": body.get("model", "reasoning"),
    }
    if _db.ready:
        await _db.store_task(task_data)

    # Execute async
    import asyncio
    asyncio.create_task(_run_task(task_id, body))

    return {"id": task_id, "status": "pending"}


@app.get("/v1/tasks/{task_id}")
async def get_task(task_id: str) -> dict:
    if not _db.ready:
        raise HTTPException(status_code=503, detail="Database not available")
    task = await _db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.get("/v1/tasks")
async def list_tasks(status: str | None = None, limit: int = 50) -> dict:
    if not _db.ready:
        return {"tasks": [], "total": 0}
    tasks = await _db.list_tasks(status=status, limit=limit)
    return {"tasks": tasks, "total": len(tasks)}


# =============================================================================
# Conversations
# =============================================================================


@app.get("/v1/conversations")
async def list_conversations(workspace: str | None = None, limit: int = 50) -> dict:
    if not _db.ready:
        return {"conversations": [], "total": 0}
    convs = await _db.list_conversations(workspace=workspace, limit=limit)
    return {"conversations": convs, "total": len(convs)}


@app.get("/v1/conversations/{conv_id}/messages")
async def get_conversation_messages(conv_id: str, limit: int = 100) -> dict:
    if not _db.ready:
        return {"messages": [], "total": 0}
    msgs = await _db.get_messages(conv_id, limit=limit)
    return {"messages": msgs, "total": len(msgs)}


# =============================================================================
# Events
# =============================================================================


@app.get("/v1/events/{channel}")
async def get_events(channel: str, count: int = 20) -> list[dict]:
    """Read recent events from a channel."""
    return await _events.read_latest(channel, count=count)


# =============================================================================
# Stats
# =============================================================================


@app.get("/v1/mind/stats")
async def mind_stats() -> dict:
    db_stats = await _db.stats() if _db.ready else {"ready": False}
    return {
        "db": db_stats,
        "events": _events.ready,
        "tools": _tools.list_tools() if _tools else [],
        "agents": [a.name for a in _engine.list_agents()] if _engine else [],
    }


# =============================================================================
# Internal task runner
# =============================================================================


async def _run_task(task_id: str, config: dict) -> None:
    """Execute a task through the reasoning engine."""
    if not _engine or not _db.ready:
        return

    await _db.update_task(task_id, status="running")

    if _events.ready:
        await _events.publish(
            "task.started", "task_started",
            {"task_id": task_id, "description": config.get("description", "")},
        )

    try:
        result = await _engine.process(
            message=config.get("description", ""),
            model=config.get("model"),
            specialist=config.get("specialist"),
            agent_id=config.get("agent_id"),
            tools=config.get("tools"),
            max_iterations=config.get("max_iterations", 10),
        )

        await _db.update_task(
            task_id,
            status="completed",
            result=result.get("response", ""),
            iterations=len(result.get("tool_calls", [])),
            completed_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )

        if _events.ready:
            await _events.publish(
                "task.completed", "task_completed",
                {"task_id": task_id, "latency_ms": result.get("latency_ms", 0)},
            )

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")
        await _db.update_task(task_id, status="failed", error=str(e))

        if _events.ready:
            await _events.publish(
                "task.failed", "task_failed",
                {"task_id": task_id, "error": str(e)},
            )
