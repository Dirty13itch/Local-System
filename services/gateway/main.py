"""API Gateway — central entry point for all client requests.

Routes requests to the appropriate backend services, handles auth,
rate limiting, and request/response transformation.
"""

from __future__ import annotations

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
    ModelInfo,
    SearchRequest,
    SearchResponse,
)
from local_system.utils import setup_logging

settings = get_settings()
logger = setup_logging("gateway", settings)

# Service URLs resolved from cluster config
SERVICE_URLS = {
    "inference": f"http://{settings.network.node1_host}:{settings.ports.inference}",
    "orchestrator": f"http://{settings.network.desk_host}:{settings.ports.orchestrator}",
    "rag": f"http://{settings.network.vault_host}:{settings.ports.rag}",
    "storage": f"http://{settings.network.vault_host}:{settings.ports.storage}",
    "model_manager": f"http://{settings.network.node1_host}:{settings.ports.model_manager}",
}


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
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    """Check health of all backend services."""
    client = _client(request)
    results = {}
    for name, url in SERVICE_URLS.items():
        try:
            resp = await client.get(f"{url}/health", timeout=5.0)
            results[name] = resp.json()
        except Exception as e:
            results[name] = {"status": "unreachable", "error": str(e)}
    return results


# --- Chat / Inference ---


@app.post("/v1/chat/completions", response_model=ChatResponse)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    """Forward chat completion requests to the inference service."""
    client = _client(request)
    try:
        resp = await client.post(
            f"{SERVICE_URLS['inference']}/v1/chat/completions",
            json=body.model_dump(),
            timeout=120.0,
        )
        resp.raise_for_status()
        return ChatResponse(**resp.json())
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e)) from e
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Inference service unavailable: {e}") from e


@app.post("/v1/chat/completions/stream")
async def chat_stream(request: Request, body: ChatRequest) -> StreamingResponse:
    """Stream chat completions via SSE."""
    client = _client(request)
    body.stream = True

    async def event_stream():
        async with client.stream(
            "POST",
            f"{SERVICE_URLS['inference']}/v1/chat/completions/stream",
            json=body.model_dump(),
            timeout=120.0,
        ) as resp:
            async for chunk in resp.aiter_text():
                yield chunk

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.websocket("/v1/chat/ws")
async def chat_websocket(websocket: WebSocket):
    """WebSocket endpoint for interactive chat sessions."""
    await websocket.accept()
    client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
    try:
        while True:
            data = await websocket.receive_json()
            body = ChatRequest(**data)
            async with client.stream(
                "POST",
                f"{SERVICE_URLS['inference']}/v1/chat/completions/stream",
                json=body.model_dump(),
                timeout=120.0,
            ) as resp:
                async for chunk in resp.aiter_text():
                    await websocket.send_text(chunk)
            await websocket.send_json({"type": "done"})
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    finally:
        await client.aclose()


# --- Models ---


@app.get("/v1/models", response_model=list[ModelInfo])
async def list_models(request: Request) -> list[ModelInfo]:
    """List all available models across inference nodes."""
    client = _client(request)
    try:
        resp = await client.get(f"{SERVICE_URLS['inference']}/v1/models")
        resp.raise_for_status()
        return [ModelInfo(**m) for m in resp.json()]
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# --- RAG / Search ---


@app.post("/v1/search", response_model=SearchResponse)
async def search(request: Request, body: SearchRequest) -> SearchResponse:
    """Search documents via the RAG service."""
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
    client = _client(request)
    try:
        resp = await client.get(f"{SERVICE_URLS['orchestrator']}/v1/tasks/{task_id}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
