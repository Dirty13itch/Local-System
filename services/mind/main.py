"""MIND Service — Central reasoning engine for Local-System.

The brain of the system. Provides:
  - Chat/reasoning with memory-augmented context
  - Agent workflows with tool use
  - Capability routing (chat, code, search, creative, infra)
  - Conversation persistence
  - Event-driven architecture via Redis Streams
  - Task lifecycle management
  - Workspace-aware context switching

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
from .workspace_manager import WorkspaceManager

settings = get_settings()
logger = setup_logging("mind", settings)

# --- Service components ---
_db = MindDB()
_events = EventBus()
_router = CapabilityRouter()
_workspaces = WorkspaceManager()
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

    # Init workspace manager with shared DB pool and Redis client
    await _workspaces.init(
        db_pool=_db._pool,
        redis_client=_events._redis,
    )

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
        "workspaces": len(_workspaces.list_workspaces()),
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
    version="0.2.0",
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
            version="0.2.0",
            node=settings.node.name.value,
            uptime_seconds=time.time() - app.state.start_time,
        ).model_dump(),
        "components": {
            "db": _db.ready,
            "events": _events.ready,
            "tools": _tools.list_tools() if _tools else [],
            "agents": [a.name for a in _engine.list_agents()] if _engine else [],
            "workspaces": len(_workspaces.list_workspaces()),
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

    # Resolve workspace if session_id provided
    workspace = None
    session_id = getattr(req, "session_id", None)
    if session_id:
        workspace = await _workspaces.get_active_workspace(session_id)

    result = await _engine.process(
        message=user_message,
        conversation_id=req.conversation_id,
        model=req.model,
        stream=req.stream,
        workspace=workspace,
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
        "workspace": result.get("workspace"),
        "latency_ms": result["latency_ms"],
    }


@app.post("/v1/mind/process")
async def process_message(body: dict) -> dict:
    """Process a message through the MIND reasoning loop.

    More flexible than chat/completions — supports specialist routing,
    agent selection, tool overrides, and workspace context.
    """
    if not _engine:
        raise HTTPException(status_code=503, detail="Reasoning engine not initialized")

    message = body.get("message", "")
    if not message:
        raise HTTPException(status_code=400, detail="'message' is required")

    # Resolve workspace
    workspace = None
    session_id = body.get("session_id")
    workspace_slug = body.get("workspace")
    if workspace_slug:
        workspace = _workspaces.get_workspace(workspace_slug)
    elif session_id:
        workspace = await _workspaces.get_active_workspace(session_id)

    return await _engine.process(
        message=message,
        conversation_id=body.get("conversation_id"),
        model=body.get("model"),
        specialist=body.get("specialist"),
        agent_id=body.get("agent_id"),
        tools=body.get("tools"),
        max_iterations=body.get("max_iterations"),
        workspace=workspace,
    )


# =============================================================================
# Workspaces
# =============================================================================


@app.get("/v1/workspaces")
async def list_workspaces() -> dict:
    """List all available workspaces."""
    workspaces = _workspaces.list_workspaces()
    return {"workspaces": workspaces, "total": len(workspaces)}


@app.get("/v1/workspaces/{slug}")
async def get_workspace(slug: str) -> dict:
    """Get a workspace by slug."""
    ws = _workspaces.get_workspace(slug)
    if not ws:
        raise HTTPException(status_code=404, detail=f"Workspace '{slug}' not found")
    return {
        "slug": ws.slug,
        "name": ws.name,
        "type": ws.workspace_type,
        "icon": ws.icon,
        "description": ws.description,
        "default_model": ws.default_model,
        "persona": ws.persona,
        "tools": ws.tools,
        "memory_tiers": ws.memory_tiers,
    }


@app.get("/v1/workspaces/active/{session_id}")
async def get_active_workspace(session_id: str) -> dict:
    """Get the active workspace for a session."""
    ws = await _workspaces.get_active_workspace(session_id)
    return {
        "slug": ws.slug,
        "name": ws.name,
        "type": ws.workspace_type,
        "icon": ws.icon,
        "default_model": ws.default_model,
    }


@app.put("/v1/workspaces/active/{session_id}")
async def set_active_workspace(session_id: str, body: dict) -> dict:
    """Switch the active workspace for a session."""
    slug = body.get("slug", "")
    if not slug:
        raise HTTPException(status_code=400, detail="'slug' is required")

    ws = await _workspaces.set_active_workspace(session_id, slug)
    if not ws:
        raise HTTPException(status_code=404, detail=f"Workspace '{slug}' not found")

    if _events.ready:
        await _events.publish(
            "workspace.switched", "workspace_switched",
            {"session_id": session_id, "workspace": slug, "name": ws.name},
        )

    return {
        "slug": ws.slug,
        "name": ws.name,
        "type": ws.workspace_type,
        "icon": ws.icon,
        "default_model": ws.default_model,
        "tools": ws.tools,
        "memory_tiers": ws.memory_tiers,
    }


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
        "workspaces": _workspaces.list_workspaces(),
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


# =============================================================================
# Metrics
# =============================================================================


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus metrics endpoint."""
    from local_system.metrics import metrics_response, SERVICE_INFO
    SERVICE_INFO.labels(service="mind", version="0.2.0", node=settings.node.name.value).set(1)
    return metrics_response()



# =============================================================================
# Cluster Status / Daily Brief
# =============================================================================


@app.get("/v1/mind/cluster-status")
async def cluster_status() -> dict:
    """Aggregate health status from all cluster services and nodes.

    Returns a comprehensive view of the entire system for
    operational awareness and daily briefings.
    """
    import asyncio

    http = app.state.http_client
    results = {}

    async def _check(name: str, url: str):
        try:
            resp = await http.get(url, timeout=5.0)
            results[name] = {"status": "up", "data": resp.json()}
        except Exception as e:
            results[name] = {"status": "down", "error": str(e)}

    # Extract hosts (avoid nested quotes in f-strings)
    litellm_h = settings.inference.litellm_host.rstrip("/")
    reasoning_h = settings.inference.vllm_reasoning_host.rstrip("/")
    coding_h = settings.inference.vllm_coding_host.rstrip("/")
    fast_h = settings.inference.vllm_fast_host.rstrip("/")
    embedding_h = settings.inference.vllm_embedding_host.rstrip("/")

    # Check all services and inference endpoints in parallel
    checks = [
        _check("gateway", "http://localhost:8700/health"),
        _check("memory", "http://localhost:8720/health"),
        _check("mind", "http://localhost:8710/health"),
        _check("litellm", f"{litellm_h}/health"),
        _check("vllm_reasoning", f"{reasoning_h}/v1/models"),
        _check("vllm_coding", f"{coding_h}/v1/models"),
        _check("vllm_fast", f"{fast_h}/v1/models"),
        _check("vllm_embedding", f"{embedding_h}/v1/models"),
    ]
    await asyncio.gather(*checks, return_exceptions=True)

    # DB stats
    db_stats = await _db.stats() if _db.ready else {"ready": False}

    # Memory consolidation status
    memory_consolidation = "n/a"
    try:
        resp = await http.get("http://localhost:8720/v1/memory/stats", timeout=5.0)
        if resp.status_code == 200:
            memory_consolidation = resp.json()
    except Exception:
        pass

    up_count = sum(1 for v in results.values() if v["status"] == "up")
    total = len(results)

    return {
        "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "summary": f"{up_count}/{total} services healthy",
        "services": results,
        "db": db_stats,
        "memory": memory_consolidation,
        "workspaces": {
            "total": len(_workspaces.list_workspaces()),
            "loaded": [ws["slug"] for ws in _workspaces.list_workspaces()],
        },
    }
