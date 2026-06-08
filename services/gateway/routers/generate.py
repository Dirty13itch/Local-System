"""Generation routes — ComfyUI proxy, performers, drops, training, templates."""

from __future__ import annotations

import asyncio
import os
import re
import uuid as _uuid
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse

from local_system.config import get_settings
from local_system.models import (
    FaceSwapRequest,
    GenerateFaceRequest,
    GenerateImageRequest,
    GenerateImageResponse,
    GenerationStatus,
    Img2ImgRequest,
    InpaintRequest,
    PerformerInfo,
    TrainLoraRequest,
    TrainingJob,
)
from local_system.utils import setup_logging

from ..auto_gen import auto_gen, generate_prompts_llm, DROPS_DIR, REFS_DIR, OUTPUT_DIR
from ..feedback import feedback_manager
from ..scheduler import gen_scheduler
from ..pipelines import (
    PIPELINE_PRESETS,
    flux_faceid,
    flux_infiniteyou,
    flux_img2img,
    flux_inpaint,
    flux_uncensored,
    realvis_img2img,
    face_swap as build_face_swap,
)
from ..prompt_templates import fill_template, list_templates
from .auth import verify_api_key

settings = get_settings()
logger = setup_logging("gateway.generate", settings)

router = APIRouter(tags=["generate"])

# ComfyUI on WORKSHOP node
COMFYUI_URL = os.environ.get("COMFYUI_URL", f"http://{settings.network.workshop}:8188")

# Performer data path — on VAULT NFS mount
PERFORMERS_JSON = os.environ.get("PERFORMERS_JSON", "/mnt/vault/data/performers.json")
_performers_cache: list[dict] | None = None

# Performer reference photos
PERFORMER_REFS_DIR = os.environ.get("PERFORMER_REFS_DIR", "/mnt/vault/data/performer-refs")

# In-memory training job tracker
_training_jobs: dict[str, dict] = {}


def _client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


def _load_performers() -> list[dict]:
    """Load performer database from JSON file (cached)."""
    global _performers_cache
    if _performers_cache is not None:
        return _performers_cache
    import json as _json

    try:
        with open(PERFORMERS_JSON, encoding="utf-8") as f:
            _performers_cache = _json.load(f)
        logger.info("Loaded %d performers from %s", len(_performers_cache), PERFORMERS_JSON)
    except FileNotFoundError:
        logger.warning("Performers JSON not found: %s", PERFORMERS_JSON)
        _performers_cache = []
    except Exception as e:
        logger.error("Failed to load performers: %s", e)
        _performers_cache = []
    return _performers_cache


# ─── Image Generation ────────────────────────────────────────────────────


@router.post("/v1/generate/image", response_model=GenerateImageResponse)
async def generate_image(request: Request, body: GenerateImageRequest) -> GenerateImageResponse:
    """Submit text-to-image generation to ComfyUI."""
    verify_api_key(request)
    client = _client(request)

    if body.pipeline in ("flux-uncensored", "flux"):
        workflow_data = flux_uncensored(
            prompt=body.prompt, negative_prompt=body.negative_prompt,
            width=body.width, height=body.height, steps=body.steps,
            cfg=body.cfg, seed=body.seed, lora_name=body.lora_name,
            lora_strength=body.lora_strength, batch_size=body.batch_size,
        )
    elif body.pipeline == "realvis-xl":
        from ..pipelines import realvis_xl

        workflow_data = realvis_xl(
            prompt=body.prompt, negative_prompt=body.negative_prompt,
            width=body.width, height=body.height, steps=body.steps,
            cfg=body.cfg, seed=body.seed, batch_size=body.batch_size,
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown pipeline: {body.pipeline}")

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


@router.post("/v1/generate/face", response_model=GenerateImageResponse)
async def generate_face(request: Request, body: GenerateFaceRequest) -> GenerateImageResponse:
    """Identity-preserving generation using reference photo."""
    verify_api_key(request)
    client = _client(request)

    if body.pipeline == "flux-faceid":
        workflow_data = flux_faceid(
            prompt=body.prompt, reference_image=body.reference_image,
            negative_prompt=body.negative_prompt, identity_strength=body.identity_strength,
            width=body.width, height=body.height, steps=body.steps,
            cfg=body.cfg, seed=body.seed,
        )
    elif body.pipeline == "flux-infiniteyou":
        workflow_data = flux_infiniteyou(
            prompt=body.prompt, reference_image=body.reference_image,
            negative_prompt=body.negative_prompt, identity_strength=body.identity_strength,
            width=body.width, height=body.height, steps=body.steps,
            cfg=body.cfg, seed=body.seed,
        )
    elif body.pipeline == "sdxl-faceid":
        from ..pipelines import sdxl_faceid

        workflow_data = sdxl_faceid(
            prompt=body.prompt, reference_image=body.reference_image,
            negative_prompt=body.negative_prompt, identity_strength=body.identity_strength,
            width=body.width, height=body.height, steps=body.steps,
            cfg=body.cfg, seed=body.seed,
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown face pipeline: {body.pipeline}")

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


@router.post("/v1/generate/swap", response_model=GenerateImageResponse)
async def generate_swap(request: Request, body: FaceSwapRequest) -> GenerateImageResponse:
    """Face swap via ReActor."""
    verify_api_key(request)
    client = _client(request)

    workflow_data = build_face_swap(
        source_image=body.source_image,
        face_image=body.face_image,
        restore_face=body.restore_face,
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


@router.get("/v1/generate/view")
async def view_image(request: Request, filename: str, type: str = "output", subfolder: str = "") -> StreamingResponse:
    """Proxy ComfyUI image viewer."""
    client = _client(request)
    params = {"filename": filename, "type": type, "subfolder": subfolder}
    try:
        resp = await client.get(f"{COMFYUI_URL}/view", params=params, timeout=30.0)
        return StreamingResponse(
            content=resp.iter_bytes(),
            media_type=resp.headers.get("content-type", "image/png"),
        )
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/v1/generate/history")
async def generation_history(request: Request, max_items: int = 20) -> dict:
    """Get recent generation history from ComfyUI."""
    client = _client(request)
    try:
        resp = await client.get(f"{COMFYUI_URL}/history", params={"max_items": max_items}, timeout=10.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/v1/generate/queue")
async def generation_queue(request: Request) -> dict:
    """Get ComfyUI queue status."""
    client = _client(request)
    try:
        resp = await client.get(f"{COMFYUI_URL}/queue", timeout=5.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/v1/generate/status")
async def generation_status(request: Request) -> GenerationStatus:
    """Generation service status including GPU info."""
    client = _client(request)
    try:
        queue_resp = await client.get(f"{COMFYUI_URL}/queue", timeout=5.0)
        queue_data = queue_resp.json()
        running = len(queue_data.get("queue_running", []))
        pending = len(queue_data.get("queue_pending", []))
    except Exception:
        running = pending = 0

    # Query ComfyUI system stats for real GPU VRAM info
    vram_used = 0
    vram_total = 0
    try:
        sys_resp = await client.get(f"{COMFYUI_URL}/system_stats", timeout=5.0)
        sys_data = sys_resp.json()
        devices = sys_data.get("devices", [])
        if devices:
            # Sum all CUDA devices (ComfyUI reports in bytes)
            for dev in devices:
                vram_total += dev.get("vram_total", 0)
                vram_used += dev.get("vram_total", 0) - dev.get("vram_free", 0)
            vram_used = vram_used // (1024 * 1024)
            vram_total = vram_total // (1024 * 1024)
    except Exception:
        pass

    return GenerationStatus(
        active_service="comfyui",
        queue_running=running,
        queue_pending=pending,
        gpu_vram_used_mb=vram_used,
        gpu_vram_total_mb=vram_total,
    )


@router.post("/v1/generate/cancel")
async def cancel_generation(request: Request, body: dict) -> dict:
    """Cancel a running or queued generation by prompt_id."""
    client = _client(request)
    prompt_id = body.get("prompt_id", "")
    if not prompt_id:
        raise HTTPException(status_code=400, detail="prompt_id required")
    try:
        resp = await client.post(
            f"{COMFYUI_URL}/queue",
            json={"delete": [prompt_id]},
            timeout=5.0,
        )
        resp.raise_for_status()
        await client.post(f"{COMFYUI_URL}/interrupt", timeout=5.0)
        return {"status": "cancelled", "prompt_id": prompt_id}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/v1/generate/upload")
async def upload_image(request: Request) -> dict:
    """Proxy image upload to ComfyUI."""
    client = _client(request)
    body = await request.body()
    content_type = request.headers.get("content-type", "")

    try:
        resp = await client.post(
            f"{COMFYUI_URL}/upload/image",
            content=body,
            headers={"Content-Type": content_type},
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/v1/generate/models")
async def list_gen_models(request: Request) -> dict:
    """List available generation models (checkpoints, LoRAs, etc.)."""
    client = _client(request)
    try:
        resp = await client.get(f"{COMFYUI_URL}/object_info", timeout=10.0)
        resp.raise_for_status()
        data = resp.json()

        checkpoints = []
        loras = []
        if "CheckpointLoaderSimple" in data:
            ckpt_input = data["CheckpointLoaderSimple"].get("input", {}).get("required", {})
            if "ckpt_name" in ckpt_input:
                checkpoints = ckpt_input["ckpt_name"][0] if ckpt_input["ckpt_name"] else []
        if "LoraLoader" in data:
            lora_input = data["LoraLoader"].get("input", {}).get("required", {})
            if "lora_name" in lora_input:
                loras = lora_input["lora_name"][0] if lora_input["lora_name"] else []

        return {"checkpoints": checkpoints, "loras": loras}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/v1/generate/pipelines")
async def list_pipelines() -> list[dict]:
    """List available generation pipelines."""
    return [
        {"id": "flux-uncensored", "name": "FLUX Uncensored", "type": "text2img", "est_time": "45-60s"},
        {"id": "realvis-xl", "name": "RealVisXL V5.0", "type": "text2img", "est_time": "25-35s"},
        {"id": "flux-faceid", "name": "FLUX FaceID (PuLID)", "type": "face", "est_time": "60-90s"},
        {"id": "flux-infiniteyou", "name": "FLUX InfiniteYou (ByteDance)", "type": "face", "est_time": "60-90s"},
        {"id": "sdxl-faceid", "name": "SDXL FaceID (IPAdapter)", "type": "face", "est_time": "35-50s"},
        {"id": "face-swap", "name": "ReActor Face Swap", "type": "swap", "est_time": "10-15s"},
        {"id": "queen-portrait", "name": "Queen Portrait (832x1216)", "type": "queen", "est_time": "60-90s"},
        {"id": "queen-scene", "name": "Queen Scene (1344x768)", "type": "queen", "est_time": "60-90s"},
        {"id": "flux-img2img", "name": "FLUX Img2Img", "type": "img2img", "est_time": "30-50s"},
        {"id": "realvis-img2img", "name": "RealVisXL Img2Img", "type": "img2img", "est_time": "20-30s"},
        {"id": "flux-inpaint", "name": "FLUX Inpaint", "type": "inpaint", "est_time": "35-55s"},
    ]


# ─── Prompt Templates ────────────────────────────────────────────────────


@router.get("/v1/generate/templates")
async def get_templates(category: str | None = None) -> list[dict]:
    """List available prompt templates, optionally filtered by category."""
    return list_templates(category)


@router.post("/v1/generate/from-template")
async def generate_from_template(
    request: Request,
    template_id: str,
    subject: str = "beautiful woman",
    seed: int = -1,
    restore_face: bool | None = None,
) -> GenerateImageResponse:
    """Generate an image from a prompt template."""
    verify_api_key(request)
    client = _client(request)

    params = fill_template(template_id, subject)
    if not params:
        raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")

    pipeline_name = params.pop("pipeline", "flux-uncensored")
    pipeline_fn = PIPELINE_PRESETS.get(pipeline_name)
    if not pipeline_fn:
        pipeline_fn = flux_uncensored

    if restore_face is not None:
        params["restore_face"] = restore_face
    params["seed"] = seed

    workflow_data = pipeline_fn(**params)

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


# ─── Img2Img & Inpainting ────────────────────────────────────────────────


@router.post("/v1/generate/img2img", response_model=GenerateImageResponse)
async def generate_img2img(request: Request, body: Img2ImgRequest) -> GenerateImageResponse:
    """Image-to-image generation."""
    verify_api_key(request)
    client = _client(request)

    if body.pipeline == "realvis-img2img":
        workflow_data = realvis_img2img(
            prompt=body.prompt, source_image=body.source_image,
            negative_prompt=body.negative_prompt, denoise_strength=body.denoise_strength,
            width=body.width, height=body.height, steps=body.steps,
            cfg=body.cfg, seed=body.seed, restore_face=body.restore_face,
        )
    else:
        workflow_data = flux_img2img(
            prompt=body.prompt, source_image=body.source_image,
            negative_prompt=body.negative_prompt, denoise_strength=body.denoise_strength,
            width=body.width, height=body.height, steps=body.steps,
            cfg=body.cfg, seed=body.seed, lora_name=body.lora_name,
            lora_strength=body.lora_strength, restore_face=body.restore_face,
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


@router.post("/v1/generate/inpaint", response_model=GenerateImageResponse)
async def generate_inpaint(request: Request, body: InpaintRequest) -> GenerateImageResponse:
    """Inpainting — repaint only the masked region of an image."""
    verify_api_key(request)
    client = _client(request)

    workflow_data = flux_inpaint(
        prompt=body.prompt, source_image=body.source_image,
        mask_image=body.mask_image, negative_prompt=body.negative_prompt,
        denoise_strength=body.denoise_strength, width=body.width,
        height=body.height, steps=body.steps, cfg=body.cfg,
        seed=body.seed, lora_name=body.lora_name,
        lora_strength=body.lora_strength, restore_face=body.restore_face,
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


# ─── Performers ──────────────────────────────────────────────────────────


@router.get("/v1/generate/performers")
async def search_performers(
    q: str = "",
    min_rating: float = 0.0,
    min_gen_suitability: int = 0,
    tier: str | None = None,
    implants_only: bool = False,
    bimbo_subtype: str | None = None,
    favorites_only: bool = False,
    sort_by: str = "gen_suitability",
    limit: int = 50,
) -> list[PerformerInfo]:
    """Search the performer database.

    Filters:
        q: Name/alias search
        min_rating: Minimum 1-10 rating
        min_gen_suitability: Minimum 0-100 composite score
        tier: Filter by S/A/B tier
        implants_only: Only show performers with implants
        bimbo_subtype: Filter by subtype (e.g. "Tits on a Stick")
        favorites_only: Only show favorites

    Sort options: gen_suitability, rating, bimbo_score, style_match, name
    """
    performers = _load_performers()
    results = []

    for p in performers:
        # Parse rating
        rating = p.get("rating") or 0
        if isinstance(rating, str):
            try:
                rating = float(rating)
            except ValueError:
                rating = 0.0
        elif not isinstance(rating, (int, float)):
            rating = 0.0

        if rating < min_rating:
            continue

        # Gen suitability filter
        gen_suit = int(p.get("gen_suitability", 0) or 0)
        if gen_suit < min_gen_suitability:
            continue

        # Tier filter
        if tier and p.get("tier", "") != tier.upper():
            continue

        # Implants filter
        impl_raw = p.get("implants")
        if isinstance(impl_raw, bool):
            implants = impl_raw
        elif isinstance(impl_raw, str):
            implants = impl_raw.lower() in ("yes", "true", "1")
        else:
            implants = None
        if implants_only and not implants:
            continue

        # Bimbo subtype filter
        if bimbo_subtype:
            subtype = (p.get("bimbo_subtype") or "").lower()
            if bimbo_subtype.lower() not in subtype:
                continue

        # Favorites filter
        if favorites_only and not p.get("is_favorite", p.get("isFavorite", False)):
            continue

        # Name search
        if q:
            name = (p.get("name") or "").lower()
            aliases = (p.get("aliases") or "").lower()
            if q.lower() not in name and q.lower() not in aliases:
                continue

        # String-safe helpers
        def _str(key: str, fallback: str = "") -> str:
            v = p.get(key)
            return str(v) if v is not None else fallback

        def _strnone(key: str) -> str | None:
            v = p.get(key)
            return str(v) if v is not None else None

        def _intnone(key: str) -> int | None:
            v = p.get(key)
            if v is None:
                return None
            try:
                return int(v)
            except (ValueError, TypeError):
                return None

        # Count reference images for this performer
        slug = (p.get("name") or "").lower().replace(" ", "-")
        slug = re.sub(r"[^a-z0-9-]", "", slug)
        ref_count = 0
        is_subject = False
        from ..scheduler import SUBJECTS_DIR
        ref_dir = SUBJECTS_DIR / slug
        if ref_dir.exists():
            ref_count = sum(
                1 for f in ref_dir.iterdir()
                if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
            )
        # Check if active in scheduler
        is_subject = slug in gen_scheduler._subjects

        results.append(PerformerInfo(
            name=p.get("name", ""),
            aliases=_str("aliases"),
            rating=float(rating),
            gen_suitability=gen_suit,
            tier=_str("tier"),
            bimbo_score=int(p.get("bimbo_score", 0) or 0),
            bimbo_match_pct=int(p.get("bimbo_match_pct", 0) or 0),
            bimbo_subtype=_str("bimbo_subtype"),
            viewing_priority=_str("viewing_priority"),
            style_match=int(p.get("style_match", 0) or 0),
            content_areas=_str("content_areas"),
            height=_strnone("height"),
            weight=_strnone("weight"),
            bust=_strnone("bust") or _strnone("braSize"),
            waist=_strnone("waist"),
            hip=_strnone("hip"),
            bust_waist_hip=_strnone("bust_waist_hip"),
            bust_to_frame=_strnone("bust_to_frame"),
            body_type=_strnone("body_type") or _strnone("bodyType"),
            implants=implants,
            implant_status=_strnone("implant_status"),
            ethnicity=_strnone("ethnicity"),
            nationality=_strnone("nationality"),
            career_start=_strnone("career_start") or _strnone("careerStart"),
            career_end=_strnone("career_end") or _strnone("careerEnd"),
            career_peak=_strnone("career_peak"),
            years_active=_intnone("years_active"),
            total_scenes=_intnone("total_scenes"),
            studios=_str("studios"),
            signature_attributes=_str("signature_attributes"),
            content_specialization=_str("content_specialization"),
            is_favorite=p.get("is_favorite", p.get("isFavorite", False)),
            is_subject=is_subject,
            reference_count=ref_count,
        ))

    # Sort
    sort_keys = {
        "gen_suitability": lambda x: x.gen_suitability,
        "rating": lambda x: x.rating,
        "bimbo_score": lambda x: x.bimbo_score,
        "style_match": lambda x: x.style_match,
        "name": lambda x: x.name.lower(),
    }
    sort_fn = sort_keys.get(sort_by, sort_keys["gen_suitability"])
    reverse = sort_by != "name"
    results.sort(key=sort_fn, reverse=reverse)
    return results[:limit]


@router.post("/v1/generate/performers/{name}/activate")
async def activate_performer(name: str, request: Request) -> dict:
    """Activate a performer as a scheduler subject for autonomous generation.

    Creates the subject directory and registers in scheduler.
    Reference images must be placed in gen-subjects/{slug}/ separately.
    """
    body = {}
    if request.headers.get("content-type") == "application/json":
        try:
            body = await request.json()
        except Exception:
            body = {}
    priority = body.get("priority")

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    # Look up performer in DB for tier-based priority
    performers = _load_performers()
    performer = None
    for p in performers:
        p_slug = re.sub(r"[^a-z0-9]+", "-", (p.get("name") or "").lower()).strip("-")
        if p_slug == slug:
            performer = p
            break

    # Set priority based on tier if not explicitly provided
    if priority is None:
        tier = (performer or {}).get("tier", "")
        priority = {"S": 8, "A": 6, "B": 5}.get(tier, 3)

    # Create subject in scheduler
    from ..scheduler import SUBJECTS_DIR
    ref_dir = SUBJECTS_DIR / slug
    ref_dir.mkdir(parents=True, exist_ok=True)

    subject = gen_scheduler.add_subject(
        name=slug,
        display_name=name,
        priority=priority,
        mode="explicit",
        subject_type="performer",
    )

    ref_count = sum(
        1 for f in ref_dir.iterdir()
        if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    ) if ref_dir.exists() else 0

    return {
        "status": "activated",
        "slug": slug,
        "display_name": name,
        "priority": priority,
        "ref_dir": str(ref_dir),
        "ref_count": ref_count,
        "has_refs": ref_count > 0,
        "themes": len(subject.themes),
        "note": "Drop reference images into the ref_dir to enable generation" if ref_count == 0 else None,
    }


# ─── Custom Characters ──────────────────────────────────────────────────


@router.post("/v1/generate/characters")
async def create_custom_character(request: Request) -> dict:
    """Create a custom character (non-pornstar) for autonomous generation.

    Custom characters use user-provided body descriptions instead of
    looking up the performer database. Drop reference images into the
    returned ref_dir path to enable generation.
    """
    body = await request.json()
    name = body.get("name", "")
    if not name:
        raise HTTPException(status_code=400, detail="'name' is required")

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    subject = gen_scheduler.add_subject(
        name=slug,
        display_name=name,
        priority=body.get("priority", 5),
        mode=body.get("mode", "explicit"),
        themes=body.get("themes"),
        subject_type="custom",
        body_description=body.get("body_description", ""),
        appearance_notes=body.get("appearance_notes", ""),
        style_direction=body.get("style_direction", ""),
        custom_attributes=body.get("custom_attributes", ""),
    )

    from ..scheduler import SUBJECTS_DIR
    ref_dir = SUBJECTS_DIR / slug

    return {
        "status": "created",
        "slug": slug,
        "display_name": name,
        "subject_type": "custom",
        "ref_dir": str(ref_dir),
        "body_description": subject.body_description,
        "appearance_notes": subject.appearance_notes,
        "style_direction": subject.style_direction,
        "note": "Drop reference images into ref_dir to enable generation",
    }


@router.put("/v1/generate/characters/{slug}")
async def update_custom_character(slug: str, request: Request) -> dict:
    """Update a custom character's attributes."""
    subject = gen_scheduler.get_subject(slug)
    if not subject:
        raise HTTPException(status_code=404, detail=f"Character not found: {slug}")

    body = await request.json()
    if "body_description" in body:
        subject.body_description = body["body_description"]
    if "appearance_notes" in body:
        subject.appearance_notes = body["appearance_notes"]
    if "style_direction" in body:
        subject.style_direction = body["style_direction"]
    if "custom_attributes" in body:
        subject.custom_attributes = body["custom_attributes"]
    if "display_name" in body:
        subject.display_name = body["display_name"]
    if "priority" in body:
        subject.priority = body["priority"]
    if "enabled" in body:
        subject.enabled = body["enabled"]
    if "mode" in body:
        subject.mode = body["mode"]
    if "themes" in body:
        subject.themes = body["themes"]

    gen_scheduler.save_config()

    return {
        "status": "updated",
        "slug": slug,
        "subject_type": subject.subject_type,
        "body_description": subject.body_description,
        "appearance_notes": subject.appearance_notes,
        "style_direction": subject.style_direction,
    }


@router.get("/v1/generate/characters")
async def list_characters(subject_type: str | None = None) -> list[dict]:
    """List all characters/subjects (custom and performers).

    Filter by subject_type: "custom" or "performer" (or omit for all).
    """
    from ..scheduler import SUBJECTS_DIR

    results = []
    for name, s in gen_scheduler._subjects.items():
        if subject_type and s.subject_type != subject_type:
            continue

        ref_dir = SUBJECTS_DIR / name
        ref_count = sum(
            1 for f in ref_dir.iterdir()
            if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        ) if ref_dir.exists() else 0

        info = {
            "slug": name,
            "display_name": s.display_name or name,
            "subject_type": s.subject_type,
            "enabled": s.enabled,
            "has_refs": ref_count > 0,
            "ref_count": ref_count,
            "priority": s.priority,
            "mode": s.mode,
            "total_generated": s.total_generated,
            "themes": len(s.themes) if s.themes else 0,
        }
        if s.subject_type == "custom":
            info["body_description"] = s.body_description
            info["appearance_notes"] = s.appearance_notes
            info["style_direction"] = s.style_direction
        results.append(info)

    results.sort(key=lambda x: x.get("priority", 0), reverse=True)
    return results


# ─── Auto-Generation (Drop Folder) ──────────────────────────────────────


@router.get("/v1/generate/drops")
async def list_drops() -> dict:
    """List all drop folders and their processing status."""
    return auto_gen.get_status()


@router.get("/v1/generate/drops/{name}")
async def get_drop_detail(name: str) -> dict:
    """Get details for a specific drop folder."""
    entries = auto_gen.scan_drops()
    for e in entries:
        if e.name == name:
            from dataclasses import asdict

            result = asdict(e)
            manifest_path = REFS_DIR / name / "manifest.json"
            if manifest_path.exists():
                import json as _json

                result["manifest"] = _json.loads(manifest_path.read_text())
            output_dir = OUTPUT_DIR / name
            if output_dir.exists():
                result["output_images"] = [
                    f.name for f in output_dir.iterdir()
                    if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
                ]
            return result
    raise HTTPException(status_code=404, detail=f"Drop not found: {name}")


@router.post("/v1/generate/drops/{name}/process")
async def process_drop(request: Request, name: str) -> dict:
    """Manually trigger processing of a specific drop folder."""
    verify_api_key(request)
    asyncio.create_task(auto_gen.process_drop(name))
    return {"status": "processing", "name": name, "message": f"Processing started for '{name}'"}


@router.post("/v1/generate/drops/{name}/retry")
async def retry_drop(request: Request, name: str) -> dict:
    """Retry a failed drop by clearing error marker and reprocessing."""
    verify_api_key(request)

    error_marker = DROPS_DIR / name / ".error"
    done_marker = DROPS_DIR / name / ".done"

    if error_marker.exists():
        error_marker.unlink()
    if done_marker.exists():
        done_marker.unlink()

    asyncio.create_task(auto_gen.process_drop(name))
    return {"status": "retrying", "name": name}


@router.post("/v1/generate/drops/scan")
async def scan_drops_now(request: Request) -> dict:
    """Force an immediate scan and process all pending drops."""
    verify_api_key(request)

    pending = auto_gen.get_pending()
    if not pending:
        return {"message": "No pending drops", "pending": 0}

    for entry in pending:
        asyncio.create_task(auto_gen.process_drop(entry.name))

    return {
        "message": f"Processing {len(pending)} drops",
        "pending": len(pending),
        "names": [e.name for e in pending],
    }


@router.get("/v1/generate/drops/{name}/images")
async def get_drop_images(name: str) -> list[str]:
    """Get generated image URLs for a processed drop."""
    output_dir = OUTPUT_DIR / name
    if not output_dir.exists():
        return []

    images = []
    for f in sorted(output_dir.iterdir()):
        if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            images.append(f"/v1/generate/drops/{name}/image/{f.name}")
    return images


@router.get("/v1/generate/drops/{name}/image/{filename}")
async def serve_drop_image(name: str, filename: str) -> FileResponse:
    """Serve a generated image from the output folder."""
    image_path = OUTPUT_DIR / name / filename
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    ext = image_path.suffix.lower()
    content_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    return FileResponse(
        path=image_path,
        media_type=content_types.get(ext, "application/octet-stream"),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/v1/generate/drops/{name}/ref/{filename}")
async def serve_drop_ref(name: str, filename: str) -> FileResponse:
    """Serve a reference image from the refs folder."""
    image_path = REFS_DIR / name / filename
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Reference image not found")

    ext = image_path.suffix.lower()
    content_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    return FileResponse(
        path=image_path,
        media_type=content_types.get(ext, "application/octet-stream"),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/v1/generate/gallery")
async def gallery_data() -> dict:
    """Aggregated gallery data — all subjects with their generated images.

    Returns a flat list of subjects, each with image URLs, metadata, and status.
    Designed to power the /gallery web page and mobile apps.
    """
    import json as _json

    subjects = []
    if not OUTPUT_DIR.exists():
        return {"subjects": [], "total_images": 0}

    for subject_dir in sorted(OUTPUT_DIR.iterdir(), reverse=True):
        if not subject_dir.is_dir():
            continue

        name = subject_dir.name

        # Load manifest first — it contains the actual pipeline used
        manifest = {}
        manifest_path = REFS_DIR / name / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = _json.loads(manifest_path.read_text())
            except Exception:
                pass

        # Determine pipeline from manifest (accurate), not from filename
        pipeline = manifest.get("pipeline", "flux")
        identity = manifest.get("identity_method", "unknown")

        images = []
        for f in sorted(subject_dir.iterdir()):
            if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                stat = f.stat()
                images.append({
                    "filename": f.name,
                    "url": f"/v1/generate/drops/{name}/image/{f.name}",
                    "size_bytes": stat.st_size,
                    "created": stat.st_mtime,
                    "pipeline": pipeline,
                    "identity_method": identity,
                })

        if not images:
            continue

        # Check drop status
        drop_dir = DROPS_DIR / name
        status = "unknown"
        if (drop_dir / ".done").exists():
            status = "done"
        elif (drop_dir / ".error").exists():
            status = "error"
        elif drop_dir.exists():
            status = "pending"

        # Reference images
        refs = []
        ref_dir = REFS_DIR / name
        if ref_dir.exists():
            for f in sorted(ref_dir.iterdir()):
                if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                    refs.append({
                        "filename": f.name,
                        "url": f"/v1/generate/drops/{name}/ref/{f.name}",
                    })

        # Read prompts — new manifests use "prompts" (list), old ones used "prompt_used" (str)
        prompts = manifest.get("prompts", [])
        if not prompts:
            prompt_used = manifest.get("prompt_used", "")
            if prompt_used:
                prompts = [prompt_used]

        subjects.append({
            "name": name,
            "status": status,
            "image_count": len(images),
            "images": images,
            "refs": refs,
            "prompts": prompts,
            "context": manifest.get("context", ""),
            "pipeline": pipeline,
            "identity_method": identity,
            "processed_at": manifest.get("processed_at", ""),
            "latest": max(img["created"] for img in images) if images else 0,
        })

    # Sort by most recent generation
    subjects.sort(key=lambda s: s["latest"], reverse=True)
    total = sum(s["image_count"] for s in subjects)

    # Include ratings map so gallery can render rating state per-image
    ratings_map = feedback_manager.get_all_ratings_map()

    return {
        "subjects": subjects,
        "total_subjects": len(subjects),
        "total_images": total,
        "ratings": ratings_map,
        "feedback_summary": feedback_manager.summary(),
    }


# ─── Feedback & Rating Endpoints ─────────────────────────────────────────


@router.post("/v1/generate/feedback/rate")
async def rate_image(request: Request) -> dict:
    """Rate a generated image as good or bad.

    Body: { subject, filename, rating: "good"|"bad", prompt?: str, notes?: str }
    """
    body = await request.json()
    subject = body.get("subject", "")
    filename = body.get("filename", "")
    rating = body.get("rating", "")

    if not subject or not filename:
        raise HTTPException(status_code=400, detail="'subject' and 'filename' are required")
    if rating not in ("good", "bad"):
        raise HTTPException(status_code=400, detail="'rating' must be 'good' or 'bad'")

    entry = feedback_manager.rate_image(
        subject=subject,
        filename=filename,
        rating=rating,
        prompt=body.get("prompt", ""),
        notes=body.get("notes", ""),
    )
    return {
        "ok": True,
        "rating": rating,
        "subject": subject,
        "filename": filename,
        "summary": feedback_manager.summary(),
    }


@router.delete("/v1/generate/feedback/rate")
async def unrate_image(request: Request) -> dict:
    """Remove a rating from an image.

    Body: { subject, filename }
    """
    body = await request.json()
    subject = body.get("subject", "")
    filename = body.get("filename", "")

    if not subject or not filename:
        raise HTTPException(status_code=400, detail="'subject' and 'filename' are required")

    removed = feedback_manager.remove_rating(subject, filename)
    return {"ok": removed, "subject": subject, "filename": filename}


@router.get("/v1/generate/feedback/ratings")
async def get_ratings(subject: str = "", rating: str = "") -> dict:
    """Get all ratings, optionally filtered by subject and/or rating value."""
    ratings = feedback_manager.get_ratings(
        subject=subject or None,
        rating_filter=rating or None,
    )
    return {"ratings": ratings, "count": len(ratings), "summary": feedback_manager.summary()}


@router.get("/v1/generate/feedback/preferences")
async def get_preferences() -> dict:
    """Get current style preferences."""
    return {
        "preferences": feedback_manager.get_preferences(),
        "summary": feedback_manager.summary(),
    }


@router.put("/v1/generate/feedback/preferences")
async def update_preferences(request: Request) -> dict:
    """Update style preferences. Only provided fields are changed.

    Body: { like_more?, like_less?, body_notes?, mood_notes?, setting_notes?, custom? }
    """
    body = await request.json()
    prefs = feedback_manager.update_preferences(
        like_more=body.get("like_more"),
        like_less=body.get("like_less"),
        body_notes=body.get("body_notes"),
        mood_notes=body.get("mood_notes"),
        setting_notes=body.get("setting_notes"),
        custom=body.get("custom"),
    )
    return {
        "ok": True,
        "preferences": feedback_manager.get_preferences(),
        "summary": feedback_manager.summary(),
    }


@router.get("/v1/generate/feedback/summary")
async def feedback_summary() -> dict:
    """Get feedback summary with stats and active preferences."""
    return {
        **feedback_manager.summary(),
        "preferences": feedback_manager.get_preferences(),
    }


@router.get("/v1/generate/feedback/prompt-context")
async def feedback_prompt_context(subject: str = "") -> dict:
    """Preview the feedback context that would be injected into LLM prompt generation.

    Useful for debugging — shows exactly what the LLM sees about your preferences.
    """
    context = feedback_manager.get_prompt_context(subject=subject or None)
    return {"context": context, "has_feedback": bool(context)}


@router.post("/v1/generate/preview-prompts")
async def preview_prompts(request: Request) -> dict:
    """Preview what the LLM would generate as image prompts for a subject."""
    body = await request.json()
    subject = body.get("subject", "")
    count = body.get("count", 3)
    context = body.get("context", "")

    if not subject:
        raise HTTPException(status_code=400, detail="'subject' is required")

    prompts = await generate_prompts_llm(
        subject_name=subject,
        count=min(count, 6),
        context=context,
    )

    return {"subject": subject, "count": len(prompts), "prompts": prompts}


# ─── LoRA Training ───────────────────────────────────────────────────────


@router.post("/v1/generate/train")
async def start_training(request: Request, body: TrainLoraRequest) -> TrainingJob:
    """Start LoRA training — prepares dataset then trains."""
    verify_api_key(request)

    job_id = str(_uuid.uuid4())[:8]
    job = {
        "job_id": job_id,
        "status": "preparing",
        "progress": 0.0,
        "current_epoch": 0,
        "total_epochs": body.epochs,
        "eta_seconds": 0,
        "trigger_word": body.trigger_word,
        "model_type": body.model_type,
    }
    _training_jobs[job_id] = job

    async def _run_training():
        try:
            job["status"] = "preparing"
            dataset_path = body.dataset_path or f"/data/training/{body.trigger_word}"
            prep_cmd = [
                "python3", os.path.expanduser("~/dev/prepare_dataset.py"),
                dataset_path, body.trigger_word,
                "--resolution", "1024" if body.model_type == "sdxl" else "512",
            ]
            proc = await asyncio.create_subprocess_exec(
                *prep_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            if proc.returncode != 0:
                job["status"] = "failed"
                return

            job["status"] = "training"
            job["progress"] = 0.1
            train_cmd = [
                os.path.expanduser("~/dev/train-lora.sh"),
                body.model_type, body.trigger_word, dataset_path,
            ]
            proc = await asyncio.create_subprocess_exec(
                *train_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            while proc.returncode is None:
                await asyncio.sleep(5)
                try:
                    proc.poll()  # type: ignore
                except Exception:
                    pass
                if job["progress"] < 0.9:
                    job["progress"] = min(0.9, job["progress"] + 0.02)

            await proc.wait()
            if proc.returncode == 0:
                job["status"] = "completed"
                job["progress"] = 1.0
            else:
                job["status"] = "failed"
        except Exception as exc:
            logger.error("Training failed: %s", exc)
            job["status"] = "failed"

    asyncio.create_task(_run_training())

    return TrainingJob(**job)


@router.get("/v1/generate/train/{job_id}")
async def training_status(job_id: str) -> TrainingJob:
    """Get training job status."""
    job = _training_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Training job not found: {job_id}")
    return TrainingJob(**job)


@router.get("/v1/generate/train")
async def list_training_jobs() -> list[TrainingJob]:
    """List all training jobs."""
    return [TrainingJob(**j) for j in _training_jobs.values()]


# ─── Performer Reference Photos ──────────────────────────────────────────


@router.post("/v1/generate/upload-ref")
async def upload_performer_ref(request: Request) -> dict:
    """Upload a reference photo for a performer."""
    verify_api_key(request)

    form = await request.form()
    performer_name = form.get("performer_name", "")
    file = form.get("file")

    if not performer_name or not file:
        raise HTTPException(status_code=400, detail="performer_name and file are required")

    slug = re.sub(r"[^a-z0-9]+", "-", str(performer_name).lower()).strip("-")
    ref_dir = Path(PERFORMER_REFS_DIR) / slug
    ref_dir.mkdir(parents=True, exist_ok=True)

    existing = list(ref_dir.glob("ref_*.jpg")) + list(ref_dir.glob("ref_*.png"))
    next_num = len(existing) + 1
    ext = Path(file.filename).suffix.lower() if hasattr(file, "filename") and file.filename else ".jpg"
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        ext = ".jpg"

    out_path = ref_dir / f"ref_{next_num:02d}{ext}"
    content = await file.read()
    out_path.write_bytes(content)

    return {
        "performer": str(performer_name),
        "slug": slug,
        "filename": out_path.name,
        "path": str(out_path),
        "total_refs": next_num,
    }


@router.get("/v1/generate/performer-refs/{slug}")
async def list_performer_refs(slug: str) -> dict:
    """List reference photos for a performer."""
    ref_dir = Path(PERFORMER_REFS_DIR) / slug
    if not ref_dir.exists():
        return {"slug": slug, "images": [], "count": 0}

    images = sorted([
        f.name for f in ref_dir.iterdir()
        if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    ])
    return {"slug": slug, "images": images, "count": len(images)}


@router.get("/v1/generate/performer-refs/{slug}/{filename}")
async def serve_performer_ref(slug: str, filename: str) -> FileResponse:
    """Serve a performer reference photo."""
    ref_path = Path(PERFORMER_REFS_DIR) / slug / filename
    if not ref_path.exists():
        raise HTTPException(status_code=404, detail="Reference image not found")

    ext = ref_path.suffix.lower()
    ct = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    return FileResponse(
        path=ref_path,
        media_type=ct.get(ext, "application/octet-stream"),
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ─── WebSocket Progress Proxy ────────────────────────────────────────────


@router.websocket("/v1/generate/ws")
async def generation_progress_ws(websocket: WebSocket, clientId: str = ""):
    """Proxy ComfyUI WebSocket for generation progress events."""
    await websocket.accept()

    import websockets

    comfyui_ws_url = COMFYUI_URL.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{comfyui_ws_url}/ws?clientId={clientId}"

    try:
        async with websockets.connect(ws_url) as comfy_ws:
            async for message in comfy_ws:
                await websocket.send_text(message if isinstance(message, str) else message.decode())
    except WebSocketDisconnect:
        logger.debug("Generation WS client disconnected")
    except Exception as e:
        logger.warning("Generation WS proxy error: %s", e)
        try:
            await websocket.close(code=1011, reason=str(e))
        except Exception:
            pass


# ─── Auto-Generation Scheduler ───────────────────────────────────────────


@router.get("/v1/generate/scheduler")
async def scheduler_status() -> dict:
    """Get auto-generation scheduler status, subjects, and next run info."""
    return gen_scheduler.get_status()


@router.post("/v1/generate/scheduler/start")
async def scheduler_start(request: Request, interval: int | None = None) -> dict:
    """Start the auto-generation scheduler.

    Args:
        interval: Override interval in minutes (default: 120).
    """
    verify_api_key(request)
    gen_scheduler.start(interval_minutes=interval)
    return {
        "status": "started",
        "interval_minutes": gen_scheduler._state.interval_minutes,
        "subjects": len(gen_scheduler._subjects),
    }


@router.post("/v1/generate/scheduler/stop")
async def scheduler_stop(request: Request) -> dict:
    """Stop the auto-generation scheduler."""
    verify_api_key(request)
    gen_scheduler.stop()
    return {"status": "stopped"}


@router.post("/v1/generate/scheduler/trigger")
async def scheduler_trigger(request: Request) -> dict:
    """Trigger an immediate scheduled generation (bypasses interval timer).

    Optionally specify subject and/or theme to override auto-selection.
    """
    verify_api_key(request)
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    subject_name = body.get("subject")
    theme_key = body.get("theme")

    result = await gen_scheduler.create_scheduled_drop(
        subject_name=subject_name,
        theme_key=theme_key,
    )
    return result


@router.get("/v1/generate/scheduler/subjects")
async def scheduler_subjects() -> list[dict]:
    """List all registered subjects with their config and stats."""
    subjects = []
    for s in gen_scheduler._subjects.values():
        import time as _time
        info = {
            "name": s.name,
            "display_name": s.display_name or s.name,
            "enabled": s.enabled,
            "has_refs": s.has_refs,
            "ref_count": len(list(s.ref_dir.glob("*"))) if s.ref_dir.exists() else 0,
            "themes": s.themes,
            "images_per_drop": s.images_per_drop,
            "mode": s.mode,
            "priority": s.priority,
            "total_generated": s.total_generated,
            "last_theme_index": s.last_theme_index,
            "notes": s.notes,
        }
        if s.last_generated:
            info["last_generated"] = _time.strftime(
                "%Y-%m-%d %H:%M", _time.localtime(s.last_generated)
            )
        subjects.append(info)
    return subjects


@router.post("/v1/generate/scheduler/subjects")
async def scheduler_add_subject(request: Request) -> dict:
    """Register a new subject for auto-generation.

    Body: {name, display_name?, themes?, mode?, priority?, notes?}
    Reference images must be placed in /mnt/vault/data/gen-subjects/<name>/
    """
    verify_api_key(request)
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="'name' is required")

    subject = gen_scheduler.add_subject(
        name=name,
        display_name=body.get("display_name", ""),
        themes=body.get("themes"),
        mode=body.get("mode", "explicit"),
        priority=body.get("priority", 1),
    )
    if body.get("notes"):
        subject.notes = body["notes"]
        gen_scheduler.save_config()

    return {
        "status": "added",
        "name": subject.name,
        "ref_dir": str(subject.ref_dir),
        "has_refs": subject.has_refs,
    }


@router.delete("/v1/generate/scheduler/subjects/{name}")
async def scheduler_remove_subject(request: Request, name: str) -> dict:
    """Remove a subject from auto-generation (does not delete files)."""
    verify_api_key(request)
    if gen_scheduler.remove_subject(name):
        return {"status": "removed", "name": name}
    raise HTTPException(status_code=404, detail=f"Subject not found: {name}")


@router.put("/v1/generate/scheduler/config")
async def scheduler_update_config(request: Request) -> dict:
    """Update scheduler configuration.

    Body: {interval_minutes?, quiet_start?, quiet_end?, enabled?}
    """
    verify_api_key(request)
    body = await request.json()

    if "interval_minutes" in body:
        gen_scheduler._state.interval_minutes = int(body["interval_minutes"])
    if "quiet_start" in body:
        gen_scheduler._state.quiet_start = int(body["quiet_start"])
    if "quiet_end" in body:
        gen_scheduler._state.quiet_end = int(body["quiet_end"])
    if "enabled" in body:
        gen_scheduler._state.enabled = bool(body["enabled"])

    gen_scheduler.save_config()
    return gen_scheduler.get_status()
