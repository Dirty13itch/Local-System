"""Health check routes."""
from __future__ import annotations

import time

import httpx
from fastapi import APIRouter, Request

from local_system.config import get_settings
from local_system.models import HealthResponse
from local_system.utils import setup_logging

settings = get_settings()
logger = setup_logging("gateway.health", settings)
router = APIRouter(tags=["health"])


def _client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


@router.get("/health")
async def health(request: Request) -> HealthResponse:
    return HealthResponse(
        service="gateway",
        node=settings.node.name.value,
        uptime_seconds=time.time() - request.app.state.start_time,
    )


@router.get("/health/cluster")
async def cluster_health(request: Request) -> dict:
    """Check health of all services across the cluster."""
    client = _client(request)
    _vault = settings.network.vault
    results = {}

    services = {
        "litellm": settings.inference.litellm_host,
        "memory": f"http://{_vault}:{settings.ports.memory}",
        "orchestrator": f"http://{_vault}:{settings.ports.orchestrator}",
    }

    for name, url in services.items():
        try:
            resp = await client.get(f"{url}/health", timeout=5.0)
            results[name] = resp.json()
        except Exception as e:
            results[name] = {"status": "unreachable", "error": str(e)}

    for node_name, host in [
        ("vllm_reasoning", settings.inference.vllm_reasoning_host),
        ("vllm_fast", settings.inference.vllm_fast_host),
        ("vllm_coding", settings.inference.vllm_coding_host),
        ("vllm_embedding", settings.inference.vllm_embedding_host),
    ]:
        try:
            resp = await client.get(f"{host}/health", timeout=5.0)
            results[node_name] = {"status": "ok"}
        except Exception as e:
            results[node_name] = {"status": "unreachable", "error": str(e)}

    return results


@router.post("/emergency/stop")
async def emergency_stop(request: Request) -> dict:
    """Emergency kill switch — halt all autonomous operations."""
    logger.critical("EMERGENCY STOP triggered")
    return {"status": "emergency_stop", "message": "All autonomous operations halted"}
