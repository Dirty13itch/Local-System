"""EoBQ Queens — queen profiles, DNA engine, queen image generation."""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, HTTPException, Request

from local_system.config import get_settings
from local_system.models import GenerateImageResponse, QueenGenerateRequest, QueenProfile
from local_system.utils import setup_logging

from ..dna_engine import dna_to_prompt_modifiers
from ..pipelines import queen_portrait, queen_scene
from ..queens import get_queen, load_queens, reload_queens
from ..scene_builder import build_portrait_prompt, build_scene_negative, build_scene_prompt
from .auth import verify_api_key

settings = get_settings()
logger = setup_logging("gateway.queens", settings)

router = APIRouter(tags=["queens"])

_dev_host = settings.network.dev
COMFYUI_URL = os.environ.get("COMFYUI_URL", f"http://{_dev_host}:8188")


def _client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


@router.get("/v1/generate/queens")
async def list_queens() -> list[QueenProfile]:
    """List all queen profiles from the Master Document."""
    return load_queens()


@router.get("/v1/generate/queens/{queen_id}")
async def get_queen_detail(queen_id: str) -> QueenProfile:
    """Get a specific queen's full profile."""
    q = get_queen(queen_id)
    if not q:
        raise HTTPException(status_code=404, detail=f"Queen not found: {queen_id}")
    return q


@router.post("/v1/generate/queens/reload")
async def reload_queen_data(request: Request) -> dict:
    """Force reload queen profiles from Master Document."""
    verify_api_key(request)
    queens = reload_queens()
    return {"reloaded": len(queens)}


@router.post("/v1/generate/queen", response_model=GenerateImageResponse)
async def generate_queen(request: Request, body: QueenGenerateRequest) -> GenerateImageResponse:
    """Generate queen portrait or scene with face identity.

    Uses the scene builder for proper prompt construction from queen physical
    blueprint, DNA modifiers (with explicit mode), and scene descriptions.
    """
    verify_api_key(request)
    client = _client(request)

    q = get_queen(body.queen_id)
    if not q:
        raise HTTPException(status_code=404, detail=f"Queen not found: {body.queen_id}")

    if body.prompt_override:
        prompt = body.prompt_override
    elif body.mode == "scene" and body.scene_index is not None and body.scene_index < len(q.scenes):
        prompt = build_scene_prompt(q, body.scene_index, explicit=True)
    else:
        prompt = build_portrait_prompt(q, explicit=True)

    neg = build_scene_negative(explicit=True)
    ref_image = q.reference_images[0] if q.reference_images else None

    if body.mode == "scene":
        workflow_data = queen_scene(
            prompt=prompt, reference_image=ref_image, lora_name=q.lora_name,
            identity_strength=body.identity_strength, seed=body.seed,
            negative_prompt=neg,
        )
    else:
        workflow_data = queen_portrait(
            prompt=prompt, reference_image=ref_image, lora_name=q.lora_name,
            identity_strength=body.identity_strength, seed=body.seed,
            negative_prompt=neg,
        )

    try:
        resp = await client.post(f"{COMFYUI_URL}/prompt", json=workflow_data, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        return GenerateImageResponse(
            prompt_id=data.get("prompt_id", ""),
            client_id=workflow_data.get("client_id", ""),
        )
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"ComfyUI unavailable: {e}") from e


@router.post("/v1/generate/dna-prompt")
async def dna_prompt(traits: dict[str, int], explicit: bool = False) -> dict:
    """Convert 19-trait DNA profile into prompt modifiers.

    Set explicit=True for NSFW scene descriptors.
    """
    return {"modifiers": dna_to_prompt_modifiers(traits, explicit=explicit)}
