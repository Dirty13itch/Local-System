"""API Gateway — central entry point for Local-System services.

Thin dispatcher: validates requests, routes to routers, returns responses.
All domain logic lives in routers/ submodules.

Runs on DEV:8700.
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import (
    chat as chat_router,
    generate as generate_router,
    health as health_router,
    memory as memory_router,
    queens as queens_router,
    tasks as tasks_router,
    workspaces as workspaces_router,
)

from local_system.config import get_settings
from local_system.utils import setup_logging

from .auto_gen import auto_gen

settings = get_settings()
logger = setup_logging("gateway", settings)

# Allowed CORS origins — configured via env, defaults to local dev
_cors_origins = os.environ.get(
    "CORS_ORIGINS",
    f"http://localhost:3000,http://localhost:3001,http://192.168.1.189:3000,http://192.168.1.50:3000,http://{settings.network.vault}:3001,http://{settings.network.dev}:3000",
).split(",")

# ComfyUI URL — runs on WORKSHOP, shared with auto_gen scanner
COMFYUI_URL = os.environ.get("COMFYUI_URL", f"http://{settings.network.workshop}:8188")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Gateway starting", extra={"node": settings.node.name.value})
    app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
    app.state.start_time = time.time()

    # Start auto-generation scanner (watches gen-drops folder)
    auto_gen.comfyui_url = COMFYUI_URL
    auto_gen.start_scanner()

    yield

    auto_gen.stop_scanner()
    await app.state.http_client.aclose()
    logger.info("Gateway stopped")


app = FastAPI(
    title="Local-System Gateway",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router.router)
app.include_router(chat_router.router)
app.include_router(memory_router.router)
app.include_router(tasks_router.router)
app.include_router(generate_router.router)
app.include_router(queens_router.router)
app.include_router(workspaces_router.router)


# ─── Metrics ─────────────────────────────────────────────────────────────


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus metrics endpoint."""
    from local_system.metrics import metrics_response, SERVICE_INFO

    SERVICE_INFO.labels(service="gateway", version="0.3.0", node=settings.node.name.value).set(1)
    return metrics_response()
