"""Model Manager Service — model lifecycle management.

Handles downloading, converting, distributing, and monitoring models
across inference nodes. Tracks which models are loaded on which GPUs.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException

from local_system.config import get_settings
from local_system.models import HealthResponse, ModelBackend, ModelInfo, ModelPullRequest
from local_system.utils import generate_id, setup_logging

settings = get_settings()
logger = setup_logging("model-manager", settings)

# Nodes that can serve inference
INFERENCE_NODES = {
    "node1": settings.network.node1_host,
    "node2": settings.network.node2_host,
    "dev": settings.network.dev_host,
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Model Manager starting")
    app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))
    app.state.start_time = time.time()
    # Track model assignments: model_name -> {node, backend, status}
    app.state.assignments: dict[str, dict] = {}
    yield
    await app.state.http_client.aclose()
    logger.info("Model Manager stopped")


app = FastAPI(
    title="Local-System Model Manager",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(
        service="model-manager",
        node=settings.node.name.value,
        uptime_seconds=time.time() - app.state.start_time,
    )


@app.get("/v1/models/cluster")
async def cluster_models() -> dict:
    """Get models loaded across all inference nodes."""
    client: httpx.AsyncClient = app.state.http_client
    result = {}
    for node_name, host in INFERENCE_NODES.items():
        try:
            resp = await client.get(
                f"http://{host}:{settings.ports.inference}/v1/models",
                timeout=10.0,
            )
            resp.raise_for_status()
            models = resp.json()
            result[node_name] = [
                {**m, "node": node_name} for m in models
            ]
        except Exception as e:
            result[node_name] = {"error": str(e)}
    return result


@app.post("/v1/models/pull")
async def pull_model(body: ModelPullRequest) -> dict:
    """Pull/download a model to a specific node."""
    client: httpx.AsyncClient = app.state.http_client
    target_host = INFERENCE_NODES.get(body.target_node)
    if not target_host:
        raise HTTPException(status_code=400, detail=f"Unknown node: {body.target_node}")

    if body.backend == ModelBackend.OLLAMA:
        # Use Ollama's pull API
        try:
            resp = await client.post(
                f"http://{target_host}:11434/api/pull",
                json={"name": body.name, "stream": False},
                timeout=600.0,  # Models can be large
            )
            resp.raise_for_status()
            return {
                "status": "completed",
                "model": body.name,
                "node": body.target_node,
                "backend": body.backend.value,
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
    else:
        return {
            "status": "unsupported",
            "detail": f"Pull not yet implemented for {body.backend.value} backend",
        }


@app.post("/v1/models/distribute")
async def distribute_model(model: str, target_nodes: list[str] | None = None) -> dict:
    """Distribute a model to multiple nodes."""
    targets = target_nodes or list(INFERENCE_NODES.keys())
    results = {}
    for node in targets:
        try:
            result = await pull_model(
                ModelPullRequest(name=model, target_node=node)
            )
            results[node] = result
        except HTTPException as e:
            results[node] = {"error": e.detail}
    return {"model": model, "results": results}


@app.get("/v1/models/assignments")
async def get_assignments() -> dict:
    """Get current model-to-node assignments."""
    return app.state.assignments


@app.post("/v1/models/assign")
async def assign_model(model: str, node: str, backend: str = "ollama") -> dict:
    """Assign a model to a specific node."""
    app.state.assignments[model] = {
        "node": node,
        "backend": backend,
        "assigned_at": time.time(),
    }
    return {"model": model, "node": node, "backend": backend}


@app.get("/v1/gpu/status")
async def gpu_status() -> dict:
    """Get GPU utilization across all inference nodes.

    This queries nvidia-smi compatible endpoints on each node.
    """
    # Placeholder — would query node-level GPU monitoring agents
    return {
        "node1": {
            "gpus": [
                {"index": 0, "name": "RTX 5070 Ti", "vram_total_mb": 16384},
                {"index": 1, "name": "RTX 5070 Ti", "vram_total_mb": 16384},
                {"index": 2, "name": "RTX 5070 Ti", "vram_total_mb": 16384},
                {"index": 3, "name": "RTX 5070 Ti", "vram_total_mb": 16384},
                {"index": 4, "name": "RTX 4090", "vram_total_mb": 24576},
            ]
        },
        "node2": {
            "gpus": [
                {"index": 0, "name": "RTX 5090", "vram_total_mb": 32768},
                {"index": 1, "name": "RTX 5060 Ti", "vram_total_mb": 16384},
            ]
        },
        "dev": {
            "gpus": [
                {"index": 0, "name": "RTX 5060 Ti", "vram_total_mb": 16384},
            ]
        },
    }
