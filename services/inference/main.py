"""Inference Service — routes to LiteLLM/TabbyAPI/Ollama.

The proven inference stack:
  - LiteLLM (gateway) → routes all requests to appropriate backend
  - TabbyAPI + ExLlamaV2 → 70B models via tensor parallel (5090+4090)
  - Ollama GPU → 7B-14B fast models on 5070 Ti
  - Ollama CPU → fallback on EPYC 56-core

This service provides a local unified API that routes through LiteLLM,
with direct backend access when needed (e.g., model loading on TabbyAPI).
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from local_system.config import get_settings
from local_system.models import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    ModelInfo,
)
from local_system.utils import Timer, generate_id, setup_logging

from backends import BackendRouter

settings = get_settings()
logger = setup_logging("inference", settings)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Inference service starting", extra={"node": settings.node.name.value})
    app.state.router = BackendRouter(settings)
    app.state.start_time = time.time()
    await app.state.router.initialize()
    yield
    await app.state.router.shutdown()
    logger.info("Inference service stopped")


app = FastAPI(
    title="Athanor Inference",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(
        service="inference",
        node=settings.node.name.value,
        uptime_seconds=time.time() - app.state.start_time,
    )


@app.get("/v1/models")
async def list_models() -> list[ModelInfo]:
    """List all available models across all backends."""
    return await app.state.router.list_models()


@app.post("/v1/chat/completions")
async def chat(body: ChatRequest) -> ChatResponse:
    """Generate a chat completion via LiteLLM routing."""
    router: BackendRouter = app.state.router

    with Timer() as t:
        try:
            response = await router.chat(body)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except ConnectionError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

    logger.info(
        "Chat completed",
        extra={
            "model": body.model,
            "latency_ms": f"{t.elapsed_ms:.1f}",
            "tokens": response.usage.total_tokens,
        },
    )
    return response


@app.post("/v1/chat/completions/stream")
async def chat_stream(body: ChatRequest) -> StreamingResponse:
    """Stream a chat completion via SSE."""
    router: BackendRouter = app.state.router
    body.stream = True

    async def event_stream():
        try:
            async for chunk in router.chat_stream(body):
                yield f"data: {chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield f'data: {{"error": "{e}"}}\n\n'

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/v1/embeddings")
async def embed(model: str, texts: list[str]) -> dict:
    """Generate embeddings via Ollama (nomic-embed-text)."""
    router: BackendRouter = app.state.router
    try:
        return await router.embed(model, texts)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- TabbyAPI-specific endpoints (proxied) ---


@app.get("/v1/tabby/model")
async def tabby_current_model() -> dict:
    """Get the currently loaded model on TabbyAPI."""
    router: BackendRouter = app.state.router
    return await router.tabby_status()


@app.post("/v1/tabby/model/load")
async def tabby_load_model(model_name: str) -> dict:
    """Load a specific EXL2 model on TabbyAPI."""
    router: BackendRouter = app.state.router
    return await router.tabby_load_model(model_name)


@app.post("/v1/tabby/model/unload")
async def tabby_unload_model() -> dict:
    """Unload the current model from TabbyAPI."""
    router: BackendRouter = app.state.router
    return await router.tabby_unload_model()
