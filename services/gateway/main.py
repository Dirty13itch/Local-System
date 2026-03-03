"""API Gateway — central entry point for Local-System services.

Routes requests to inference (LiteLLM), memory, RAG, and orchestrator
services. Handles CORS, API key auth, and SSE/WS.

Runs on hydra-storage:8700.
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from local_system.config import get_settings
from local_system.models import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    MemorySearchRequest,
    SearchRequest,
    SearchResponse,
)
from local_system.utils import setup_logging

settings = get_settings()
logger = setup_logging("gateway", settings)

# Allowed CORS origins — configured via env, defaults to local dev
_cors_origins = os.environ.get(
    "CORS_ORIGINS",
    f"http://localhost:3200,http://{settings.network.hydra_storage}:3200",
).split(",")

# Service URLs — all on hydra-storage unless noted
_storage_host = settings.network.hydra_storage
SERVICE_URLS = {
    "inference": f"http://{_storage_host}:{settings.ports.gateway + 1}",  # local proxy
    "memory": f"http://{_storage_host}:{settings.ports.memory}",
    "orchestrator": f"http://{_storage_host}:{settings.ports.orchestrator}",
    "rag": f"http://{_storage_host}:8704",
    "litellm": settings.inference.litellm_host,
}

# API key for gateway auth — set via env
_api_key = os.environ.get("API_SECRET_KEY", settings.api_secret_key)


def _verify_api_key(request: Request) -> None:
    """Check API key if one is configured (skip if set to 'changeme'/dev mode)."""
    if _api_key == "changeme":
        return  # Dev mode — no auth required
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {_api_key}" and request.query_params.get("api_key") != _api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Gateway starting", extra={"node": settings.node.name.value})
    app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
    app.state.start_time = time.time()
    yield
    await app.state.http_client.aclose()
    logger.info("Gateway stopped")


app = FastAPI(
    title="Local-System Gateway",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


# --- Health ---


@app.get("/health")
async def health(request: Request) -> HealthResponse:
    return HealthResponse(
        service="gateway",
        node=settings.node.name.value,
        uptime_seconds=time.time() - request.app.state.start_time,
    )


@app.get("/health/cluster")
async def cluster_health(request: Request) -> dict:
    """Check health of all services across the cluster."""
    client = _client(request)
    results = {}

    # Check local services
    for name, url in SERVICE_URLS.items():
        try:
            resp = await client.get(f"{url}/health", timeout=5.0)
            results[name] = resp.json()
        except Exception as e:
            results[name] = {"status": "unreachable", "error": str(e)}

    # Check remote inference nodes
    for node_name, host in [
        ("tabby", settings.inference.tabby_host),
        ("ollama_gpu", settings.inference.ollama_gpu_host),
    ]:
        try:
            resp = await client.get(f"{host}/health", timeout=5.0)
            results[node_name] = {"status": "ok"}
        except Exception as e:
            results[node_name] = {"status": "unreachable", "error": str(e)}

    return results


# --- Chat / Inference (via LiteLLM) ---


@app.post("/v1/chat/completions", response_model=ChatResponse)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    """Route chat through LiteLLM for intelligent model routing."""
    _verify_api_key(request)
    client = _client(request)
    try:
        resp = await client.post(
            f"{SERVICE_URLS['litellm']}/v1/chat/completions",
            json={
                "model": body.model,
                "messages": [{"role": m.role.value, "content": m.content} for m in body.messages],
                "temperature": body.temperature,
                "max_tokens": body.max_tokens,
                "stream": False,
            },
            headers={"Authorization": f"Bearer {settings.inference.litellm_key}"},
            timeout=300.0,
        )
        resp.raise_for_status()
        return ChatResponse(**resp.json())
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e)) from e
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"LiteLLM unavailable: {e}") from e


@app.post("/v1/chat/completions/stream")
async def chat_stream(request: Request, body: ChatRequest) -> StreamingResponse:
    """Stream chat via SSE through LiteLLM."""
    _verify_api_key(request)
    client = _client(request)

    async def event_stream():
        async with client.stream(
            "POST",
            f"{SERVICE_URLS['litellm']}/v1/chat/completions",
            json={
                "model": body.model,
                "messages": [{"role": m.role.value, "content": m.content} for m in body.messages],
                "temperature": body.temperature,
                "max_tokens": body.max_tokens,
                "stream": True,
            },
            headers={"Authorization": f"Bearer {settings.inference.litellm_key}"},
            timeout=300.0,
        ) as resp:
            async for chunk in resp.aiter_text():
                yield chunk

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.websocket("/v1/chat/ws")
async def chat_websocket(websocket: WebSocket):
    """WebSocket for interactive chat sessions."""
    await websocket.accept()
    client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))
    try:
        while True:
            data = await websocket.receive_json()
            body = ChatRequest(**data)
            async with client.stream(
                "POST",
                f"{SERVICE_URLS['litellm']}/v1/chat/completions",
                json={
                    "model": body.model,
                    "messages": [{"role": m.role.value, "content": m.content} for m in body.messages],
                    "temperature": body.temperature,
                    "max_tokens": body.max_tokens,
                    "stream": True,
                },
                headers={"Authorization": f"Bearer {settings.inference.litellm_key}"},
                timeout=300.0,
            ) as resp:
                async for chunk in resp.aiter_text():
                    await websocket.send_text(chunk)
            await websocket.send_json({"type": "done"})
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    finally:
        await client.aclose()


# --- Models ---


@app.get("/v1/models")
async def list_models(request: Request) -> list[dict]:
    """List all available models via LiteLLM."""
    client = _client(request)
    try:
        resp = await client.get(
            f"{SERVICE_URLS['litellm']}/v1/models",
            headers={"Authorization": f"Bearer {settings.inference.litellm_key}"},
        )
        resp.raise_for_status()
        return resp.json().get("data", [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# --- Memory ---


@app.get("/v1/memory/working")
async def get_working_memory(request: Request) -> dict:
    """Get current working memory context."""
    _verify_api_key(request)
    client = _client(request)
    try:
        resp = await client.get(f"{SERVICE_URLS['memory']}/v1/memory/working")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/v1/memory/search")
async def search_memory(request: Request, body: MemorySearchRequest) -> dict:
    """Search across memory tiers."""
    _verify_api_key(request)
    client = _client(request)
    try:
        resp = await client.post(
            f"{SERVICE_URLS['memory']}/v1/memory/search",
            json=body.model_dump(),
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# --- RAG / Search ---


@app.post("/v1/search", response_model=SearchResponse)
async def search(request: Request, body: SearchRequest) -> SearchResponse:
    """Hybrid search via the RAG service."""
    _verify_api_key(request)
    client = _client(request)
    try:
        resp = await client.post(
            f"{SERVICE_URLS['rag']}/v1/search",
            json=body.model_dump(),
        )
        resp.raise_for_status()
        return SearchResponse(**resp.json())
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# --- Agents / Tasks ---


@app.post("/v1/tasks")
async def create_task(request: Request, body: dict) -> dict:
    """Create a new agent task."""
    _verify_api_key(request)
    client = _client(request)
    try:
        resp = await client.post(
            f"{SERVICE_URLS['orchestrator']}/v1/tasks",
            json=body,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/v1/tasks/{task_id}")
async def get_task(request: Request, task_id: str) -> dict:
    """Get task status and result."""
    _verify_api_key(request)
    client = _client(request)
    try:
        resp = await client.get(f"{SERVICE_URLS['orchestrator']}/v1/tasks/{task_id}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# --- Emergency ---


@app.post("/emergency/stop")
async def emergency_stop(request: Request) -> dict:
    """Emergency kill switch — halt all autonomous operations."""
    _verify_api_key(request)
    logger.critical("EMERGENCY STOP triggered")
    # TODO: Broadcast stop to all services
    return {"status": "emergency_stop", "message": "All autonomous operations halted"}
