"""Memory & search routes — proxy to memory service, with merged RAG."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Request

from local_system.config import get_settings
from local_system.models import (
    MemorySearchRequest,
    SearchRequest,
    SearchResponse,
)

settings = get_settings()
router = APIRouter(tags=["memory"])

_vault = settings.network.vault


def _client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


@router.get("/v1/memory/working")
async def get_working_memory(request: Request) -> dict:
    """Get current working memory context."""
    client = _client(request)
    try:
        resp = await client.get(f"http://{_vault}:{settings.ports.memory}/v1/memory/working")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/v1/memory/search")
async def search_memory(request: Request, body: MemorySearchRequest) -> dict:
    """Search across memory tiers."""
    client = _client(request)
    try:
        resp = await client.post(
            f"http://{_vault}:{settings.ports.memory}/v1/memory/search",
            json=body.model_dump(),
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/v1/search", response_model=SearchResponse)
async def search(request: Request, body: SearchRequest) -> SearchResponse:
    """Hybrid search via the RAG service."""
    client = _client(request)
    try:
        resp = await client.post(
            f"http://{_vault}:{settings.ports.memory}/v1/search",
            json=body.model_dump(),
        )
        resp.raise_for_status()
        return SearchResponse(**resp.json())
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
