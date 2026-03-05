"""Workspace routes — proxy to MIND service."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Request

from local_system.config import get_settings

settings = get_settings()
router = APIRouter(tags=["workspaces"])

_dev = settings.network.dev


def _client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


@router.get("/v1/workspaces")
async def list_workspaces(request: Request) -> dict:
    """List all workspaces."""
    client = _client(request)
    try:
        resp = await client.get(f"http://{_dev}:{settings.ports.mind}/v1/workspaces")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/v1/workspaces/{slug}")
async def get_workspace(request: Request, slug: str) -> dict:
    """Get workspace by slug."""
    client = _client(request)
    try:
        resp = await client.get(f"http://{_dev}:{settings.ports.mind}/v1/workspaces/{slug}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/v1/workspaces/active/{session_id}")
async def get_active(request: Request, session_id: str) -> dict:
    """Get active workspace for session."""
    client = _client(request)
    try:
        resp = await client.get(
            f"http://{_dev}:{settings.ports.mind}/v1/workspaces/active/{session_id}"
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.put("/v1/workspaces/active/{session_id}")
async def set_active(request: Request, session_id: str, body: dict) -> dict:
    """Switch active workspace for session."""
    client = _client(request)
    try:
        resp = await client.put(
            f"http://{_dev}:{settings.ports.mind}/v1/workspaces/active/{session_id}",
            json=body,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
