"""Agent task routes — proxy to orchestrator service."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Request

from local_system.config import get_settings

settings = get_settings()
router = APIRouter(tags=["tasks"])

_vault = settings.network.vault


def _client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


@router.post("/v1/tasks")
async def create_task(request: Request, body: dict) -> dict:
    """Create a new agent task."""
    client = _client(request)
    try:
        resp = await client.post(
            f"http://{_vault}:{settings.ports.orchestrator}/v1/tasks",
            json=body,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/v1/tasks/{task_id}")
async def get_task(request: Request, task_id: str) -> dict:
    """Get task status and result."""
    client = _client(request)
    try:
        resp = await client.get(
            f"http://{_vault}:{settings.ports.orchestrator}/v1/tasks/{task_id}"
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
