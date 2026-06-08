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

# Memory service is co-located on DEV with Gateway
_memory_host = "127.0.0.1"


def _client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


@router.get("/v1/memory/working")
async def get_working_memory(request: Request) -> dict:
    """Get current working memory context."""
    client = _client(request)
    try:
        resp = await client.get(f"http://{_memory_host}:{settings.ports.memory}/v1/memory/working")
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
            f"http://{_memory_host}:{settings.ports.memory}/v1/memory/search",
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
            f"http://{_memory_host}:{settings.ports.memory}/v1/search",
            json=body.model_dump(),
        )
        resp.raise_for_status()
        return SearchResponse(**resp.json())
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/v1/memory/stats")
async def memory_stats(request: Request) -> dict:
    """Get per-tier memory statistics."""
    client = _client(request)
    try:
        resp = await client.get(
            f"http://{_memory_host}:{settings.ports.memory}/v1/memory/stats",
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/v1/memory/store")
async def store_memory(request: Request) -> dict:
    """Store content to any memory tier."""
    client = _client(request)
    body = await request.json()
    try:
        resp = await client.post(
            f"http://{_memory_host}:{settings.ports.memory}/v1/memory/store",
            json=body,
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/v1/memory/consolidate")
async def consolidate_memory(request: Request) -> dict:
    """Trigger memory consolidation pipeline."""
    client = _client(request)
    try:
        resp = await client.post(
            f"http://{_memory_host}:{settings.ports.memory}/v1/memory/consolidate",
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/v1/memory/episodic")
async def list_episodic(request: Request) -> list:
    """List recent episodic events."""
    client = _client(request)
    try:
        params = dict(request.query_params)
        resp = await client.get(
            f"http://{_memory_host}:{settings.ports.memory}/v1/memory/episodic",
            params=params,
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/v1/collections")
async def list_collections(request: Request) -> list:
    """List Qdrant vector collections with point counts."""
    client = _client(request)
    try:
        # Query Qdrant directly for collection info
        qdrant_host = settings.qdrant.host
        qdrant_port = settings.qdrant.port
        resp = await client.get(
            f"http://{qdrant_host}:{qdrant_port}/collections",
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

        collections = []
        for col in data.get("result", {}).get("collections", []):
            name = col.get("name", "")
            # Get detailed info for each collection
            try:
                detail_resp = await client.get(
                    f"http://{qdrant_host}:{qdrant_port}/collections/{name}",
                    timeout=5.0,
                )
                detail_resp.raise_for_status()
                detail = detail_resp.json().get("result", {})
                collections.append({
                    "name": name,
                    "vectors_count": detail.get("vectors_count", 0),
                    "points_count": detail.get("points_count", 0),
                })
            except Exception:
                collections.append({"name": name, "vectors_count": 0, "points_count": 0})

        return collections
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
