"""API Gateway — central entry point for Local-System services.

Routes requests to inference (LiteLLM), memory, RAG, and orchestrator
services. Handles CORS, API key auth, and SSE/WS.

Runs on VAULT:8700.
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from local_system.config import get_settings
from local_system.models import (
    ChatRequest,
    ChatResponse,
    FaceSwapRequest,
    GenerateFaceRequest,
    GenerateImageRequest,
    GenerateImageResponse,
    GenerationStatus,
    HealthResponse,
    Img2ImgRequest,
    InpaintRequest,
    MemorySearchRequest,
    Message,
    PerformerInfo,
    QueenGenerateRequest,
    QueenProfile,
    SearchRequest,
    SearchResponse,
    TokenUsage,
    TrainLoraRequest,
    TrainingJob,
)
from local_system.utils import setup_logging

from .auto_gen import auto_gen, generate_prompts_llm
from .dna_engine import dna_to_prompt_modifiers
from .pipelines import (
    PIPELINE_PRESETS, flux_faceid, flux_img2img, flux_inpaint, flux_uncensored,
    queen_portrait, queen_scene, realvis_img2img, face_swap as build_face_swap,
)
from .prompt_templates import fill_template, get_template, list_templates
from .queens import get_queen, load_queens, reload_queens
from .scene_builder import build_portrait_prompt, build_scene_negative, build_scene_prompt

settings = get_settings()
logger = setup_logging("gateway", settings)

# Allowed CORS origins — configured via env, defaults to local dev
_cors_origins = os.environ.get(
    "CORS_ORIGINS",
    f"http://localhost:3001,http://{settings.network.vault}:3001",
).split(",")

# Service URLs — all on VAULT unless noted
_vault_host = settings.network.vault
SERVICE_URLS = {
    "inference": f"http://{_vault_host}:{settings.ports.gateway + 1}",  # local proxy
    "memory": f"http://{_vault_host}:{settings.ports.memory}",
    "orchestrator": f"http://{_vault_host}:{settings.ports.orchestrator}",
    "rag": f"http://{_vault_host}:8704",
    "litellm": settings.inference.litellm_host,
}

# ComfyUI on DEV node
_dev_host = settings.network.dev
COMFYUI_URL = os.environ.get("COMFYUI_URL", f"http://{_dev_host}:8188")

# Performer data path — on VAULT NFS mount
PERFORMERS_JSON = os.environ.get(
    "PERFORMERS_JSON",
    "/mnt/vault/data/performers.json",
)

# Cached performer data
_performers_cache: list[dict] | None = None

# API key for gateway auth — set via env
_api_key = os.environ.get("API_SECRET_KEY", settings.api_secret_key)


def _verify_api_key(request: Request) -> None:
    """Check API key if one is configured (skip if set to 'changeme'/dev mode)."""
    if _api_key == "changeme":
        return  # Dev mode — no auth required
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {_api_key}" and request.query_params.get("api_key") != _api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


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
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


# --- Health ---


@app.get("/health")
async def health(request: Request) -> HealthResponse:
    return HealthResponse(
        service="gateway",
        node=settings.node.name.value,
        uptime_seconds=time.time() - request.app.state.start_time,
    )


@app.get("/health/cluster")
async def cluster_health(request: Request) -> dict:
    """Check health of all services across the cluster."""
    client = _client(request)
    results = {}

    # Check local services
    for name, url in SERVICE_URLS.items():
        try:
            resp = await client.get(f"{url}/health", timeout=5.0)
            results[name] = resp.json()
        except Exception as e:
            results[name] = {"status": "unreachable", "error": str(e)}

    # Check remote inference nodes
    for node_name, host in [
        ("vllm_reasoning", settings.inference.vllm_reasoning_host),
        ("vllm_fast", settings.inference.vllm_fast_host),
    ]:
        try:
            resp = await client.get(f"{host}/health", timeout=5.0)
            results[node_name] = {"status": "ok"}
        except Exception as e:
            results[node_name] = {"status": "unreachable", "error": str(e)}

    return results


# --- Chat / Inference (via LiteLLM) ---


@app.post("/v1/chat/completions", response_model=ChatResponse)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    """Route chat through LiteLLM for intelligent model routing."""
    _verify_api_key(request)
    client = _client(request)
    try:
        resp = await client.post(
            f"{SERVICE_URLS['litellm']}/v1/chat/completions",
            json={
                "model": body.model,
                "messages": [{"role": m.role.value, "content": m.content} for m in body.messages],
                "temperature": body.temperature,
                "max_tokens": body.max_tokens,
                "stream": False,
            },
            headers={"Authorization": f"Bearer {settings.inference.litellm_key}"},
            timeout=300.0,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        return ChatResponse(
            id=data["id"],
            model=data["model"],
            message=Message(role=choice["message"]["role"], content=choice["message"]["content"]),
            usage=TokenUsage(**data.get("usage", {})),
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e)) from e
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"LiteLLM unavailable: {e}") from e


@app.post("/v1/chat/completions/stream")
async def chat_stream(request: Request, body: ChatRequest) -> StreamingResponse:
    """Stream chat via SSE through LiteLLM."""
    _verify_api_key(request)
    client = _client(request)

    async def event_stream():
        async with client.stream(
            "POST",
            f"{SERVICE_URLS['litellm']}/v1/chat/completions",
            json={
                "model": body.model,
                "messages": [{"role": m.role.value, "content": m.content} for m in body.messages],
                "temperature": body.temperature,
                "max_tokens": body.max_tokens,
                "stream": True,
            },
            headers={"Authorization": f"Bearer {settings.inference.litellm_key}"},
            timeout=300.0,
        ) as resp:
            async for chunk in resp.aiter_text():
                yield chunk

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.websocket("/v1/chat/ws")
async def chat_websocket(websocket: WebSocket):
    """WebSocket for interactive chat sessions."""
    await websocket.accept()
    client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))
    try:
        while True:
            data = await websocket.receive_json()
            body = ChatRequest(**data)
            async with client.stream(
                "POST",
                f"{SERVICE_URLS['litellm']}/v1/chat/completions",
                json={
                    "model": body.model,
                    "messages": [{"role": m.role.value, "content": m.content} for m in body.messages],
                    "temperature": body.temperature,
                    "max_tokens": body.max_tokens,
                    "stream": True,
                },
                headers={"Authorization": f"Bearer {settings.inference.litellm_key}"},
                timeout=300.0,
            ) as resp:
                async for chunk in resp.aiter_text():
                    await websocket.send_text(chunk)
            await websocket.send_json({"type": "done"})
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    finally:
        await client.aclose()


# --- Models ---


@app.get("/v1/models")
async def list_models(request: Request) -> list[dict]:
    """List all available models via LiteLLM."""
    client = _client(request)
    try:
        resp = await client.get(
            f"{SERVICE_URLS['litellm']}/v1/models",
            headers={"Authorization": f"Bearer {settings.inference.litellm_key}"},
        )
        resp.raise_for_status()
        return resp.json().get("data", [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# --- Memory ---


@app.get("/v1/memory/working")
async def get_working_memory(request: Request) -> dict:
    """Get current working memory context."""
    _verify_api_key(request)
    client = _client(request)
    try:
        resp = await client.get(f"{SERVICE_URLS['memory']}/v1/memory/working")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/v1/memory/search")
async def search_memory(request: Request, body: MemorySearchRequest) -> dict:
    """Search across memory tiers."""
    _verify_api_key(request)
    client = _client(request)
    try:
        resp = await client.post(
            f"{SERVICE_URLS['memory']}/v1/memory/search",
            json=body.model_dump(),
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# --- RAG / Search ---


@app.post("/v1/search", response_model=SearchResponse)
async def search(request: Request, body: SearchRequest) -> SearchResponse:
    """Hybrid search via the RAG service."""
    _verify_api_key(request)
    client = _client(request)
    try:
        resp = await client.post(
            f"{SERVICE_URLS['rag']}/v1/search",
            json=body.model_dump(),
        )
        resp.raise_for_status()
        return SearchResponse(**resp.json())
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# --- Agents / Tasks ---


@app.post("/v1/tasks")
async def create_task(request: Request, body: dict) -> dict:
    """Create a new agent task."""
    _verify_api_key(request)
    client = _client(request)
    try:
        resp = await client.post(
            f"{SERVICE_URLS['orchestrator']}/v1/tasks",
            json=body,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/v1/tasks/{task_id}")
async def get_task(request: Request, task_id: str) -> dict:
    """Get task status and result."""
    _verify_api_key(request)
    client = _client(request)
    try:
        resp = await client.get(f"{SERVICE_URLS['orchestrator']}/v1/tasks/{task_id}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# --- Emergency ---


@app.post("/emergency/stop")
async def emergency_stop(request: Request) -> dict:
    """Emergency kill switch — halt all autonomous operations."""
    _verify_api_key(request)
    logger.critical("EMERGENCY STOP triggered")
    # TODO: Broadcast stop to all services
    return {"status": "emergency_stop", "message": "All autonomous operations halted"}


# ─── Generation (proxy to ComfyUI) ────────────────────────────────────────


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


@app.post("/v1/generate/image", response_model=GenerateImageResponse)
async def generate_image(request: Request, body: GenerateImageRequest) -> GenerateImageResponse:
    """Submit text-to-image generation to ComfyUI."""
    _verify_api_key(request)
    client = _client(request)

    # Build workflow from preset
    if body.pipeline in ("flux-uncensored", "flux"):
        workflow_data = flux_uncensored(
            prompt=body.prompt, negative_prompt=body.negative_prompt,
            width=body.width, height=body.height, steps=body.steps,
            cfg=body.cfg, seed=body.seed, lora_name=body.lora_name,
            lora_strength=body.lora_strength, batch_size=body.batch_size,
        )
    elif body.pipeline == "realvis-xl":
        from .pipelines import realvis_xl
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


@app.post("/v1/generate/face", response_model=GenerateImageResponse)
async def generate_face(request: Request, body: GenerateFaceRequest) -> GenerateImageResponse:
    """Identity-preserving generation using reference photo."""
    _verify_api_key(request)
    client = _client(request)

    if body.pipeline == "flux-faceid":
        workflow_data = flux_faceid(
            prompt=body.prompt, reference_image=body.reference_image,
            negative_prompt=body.negative_prompt, identity_strength=body.identity_strength,
            width=body.width, height=body.height, steps=body.steps,
            cfg=body.cfg, seed=body.seed,
        )
    elif body.pipeline == "sdxl-faceid":
        from .pipelines import sdxl_faceid
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


@app.post("/v1/generate/swap", response_model=GenerateImageResponse)
async def generate_swap(request: Request, body: FaceSwapRequest) -> GenerateImageResponse:
    """Face swap via ReActor."""
    _verify_api_key(request)
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


@app.get("/v1/generate/view")
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


@app.get("/v1/generate/history")
async def generation_history(request: Request, max_items: int = 20) -> dict:
    """Get recent generation history from ComfyUI."""
    client = _client(request)
    try:
        resp = await client.get(f"{COMFYUI_URL}/history", params={"max_items": max_items}, timeout=10.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/v1/generate/queue")
async def generation_queue(request: Request) -> dict:
    """Get ComfyUI queue status."""
    client = _client(request)
    try:
        resp = await client.get(f"{COMFYUI_URL}/queue", timeout=5.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.get("/v1/generate/status")
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

    return GenerationStatus(
        active_service="comfyui",
        queue_running=running,
        queue_pending=pending,
        gpu_vram_used_mb=0,
        gpu_vram_total_mb=16384,
    )


@app.post("/v1/generate/cancel")
async def cancel_generation(request: Request, body: dict) -> dict:
    """Cancel a running or queued generation by prompt_id."""
    client = _client(request)
    prompt_id = body.get("prompt_id", "")
    if not prompt_id:
        raise HTTPException(status_code=400, detail="prompt_id required")
    try:
        # ComfyUI cancel API — delete from queue
        resp = await client.post(
            f"{COMFYUI_URL}/queue",
            json={"delete": [prompt_id]},
            timeout=5.0,
        )
        resp.raise_for_status()
        # Also try interrupt (stops currently running)
        await client.post(f"{COMFYUI_URL}/interrupt", timeout=5.0)
        return {"status": "cancelled", "prompt_id": prompt_id}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/v1/generate/upload")
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


@app.get("/v1/generate/models")
async def list_gen_models(request: Request) -> dict:
    """List available generation models (checkpoints, LoRAs, etc.)."""
    client = _client(request)
    try:
        resp = await client.get(f"{COMFYUI_URL}/object_info", timeout=10.0)
        resp.raise_for_status()
        data = resp.json()

        # Extract model lists from CheckpointLoaderSimple and LoraLoader nodes
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


@app.get("/v1/generate/pipelines")
async def list_pipelines() -> list[dict]:
    """List available generation pipelines."""
    return [
        {"id": "flux-uncensored", "name": "FLUX Uncensored", "type": "text2img", "est_time": "45-60s"},
        {"id": "realvis-xl", "name": "RealVisXL V5.0", "type": "text2img", "est_time": "25-35s"},
        {"id": "flux-faceid", "name": "FLUX FaceID (PuLID)", "type": "face", "est_time": "60-90s"},
        {"id": "sdxl-faceid", "name": "SDXL FaceID (IPAdapter)", "type": "face", "est_time": "35-50s"},
        {"id": "face-swap", "name": "ReActor Face Swap", "type": "swap", "est_time": "10-15s"},
        {"id": "queen-portrait", "name": "Queen Portrait (832x1216)", "type": "queen", "est_time": "60-90s"},
        {"id": "queen-scene", "name": "Queen Scene (1344x768)", "type": "queen", "est_time": "60-90s"},
        {"id": "flux-img2img", "name": "FLUX Img2Img", "type": "img2img", "est_time": "30-50s"},
        {"id": "realvis-img2img", "name": "RealVisXL Img2Img", "type": "img2img", "est_time": "20-30s"},
        {"id": "flux-inpaint", "name": "FLUX Inpaint", "type": "inpaint", "est_time": "35-55s"},
    ]


# ─── EoBQ Queens ──────────────────────────────────────────────────────────


@app.get("/v1/generate/queens")
async def list_queens() -> list[QueenProfile]:
    """List all queen profiles from the Master Document."""
    return load_queens()


@app.get("/v1/generate/queens/{queen_id}")
async def get_queen_detail(queen_id: str) -> QueenProfile:
    """Get a specific queen's full profile."""
    q = get_queen(queen_id)
    if not q:
        raise HTTPException(status_code=404, detail=f"Queen not found: {queen_id}")
    return q


@app.post("/v1/generate/queens/reload")
async def reload_queen_data(request: Request) -> dict:
    """Force reload queen profiles from Master Document."""
    _verify_api_key(request)
    queens = reload_queens()
    return {"reloaded": len(queens)}


@app.post("/v1/generate/queen", response_model=GenerateImageResponse)
async def generate_queen(request: Request, body: QueenGenerateRequest) -> GenerateImageResponse:
    """Generate queen portrait or scene with face identity.

    Uses the scene builder for proper prompt construction from queen physical
    blueprint, DNA modifiers (with explicit mode), and scene descriptions.
    """
    _verify_api_key(request)
    client = _client(request)

    q = get_queen(body.queen_id)
    if not q:
        raise HTTPException(status_code=404, detail=f"Queen not found: {body.queen_id}")

    # Build prompt using scene builder (explicit mode enabled)
    if body.prompt_override:
        prompt = body.prompt_override
    elif body.mode == "scene" and body.scene_index is not None and body.scene_index < len(q.scenes):
        prompt = build_scene_prompt(q, body.scene_index, explicit=True)
    else:
        prompt = build_portrait_prompt(q, explicit=True)

    # Negative prompt with anti-censorship tags
    neg = build_scene_negative(explicit=True)

    # Choose reference image (first available)
    ref_image = q.reference_images[0] if q.reference_images else None

    # Build workflow
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


@app.post("/v1/generate/dna-prompt")
async def dna_prompt(traits: dict[str, int], explicit: bool = False) -> dict:
    """Convert 19-trait DNA profile into prompt modifiers.

    Set explicit=True for NSFW scene descriptors (body positioning, clothing
    state, expression intensity, etc.) in addition to aesthetic modifiers.
    """
    return {"modifiers": dna_to_prompt_modifiers(traits, explicit=explicit)}


# ─── Prompt Templates ─────────────────────────────────────────────────────


@app.get("/v1/generate/templates")
async def get_templates(category: str | None = None) -> list[dict]:
    """List available prompt templates, optionally filtered by category.

    Categories: character_portrait, intimate_portrait, glamour, explicit_scene
    """
    return list_templates(category)


@app.post("/v1/generate/from-template")
async def generate_from_template(
    request: Request,
    template_id: str,
    subject: str = "beautiful woman",
    seed: int = -1,
    restore_face: bool | None = None,
) -> GenerateImageResponse:
    """Generate an image from a prompt template.

    Fills the template's {subject} placeholder with the provided subject
    description and submits to ComfyUI using the template's recommended
    pipeline and dimensions.
    """
    _verify_api_key(request)
    client = _client(request)

    params = fill_template(template_id, subject)
    if not params:
        raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")

    pipeline_name = params.pop("pipeline", "flux-uncensored")
    pipeline_fn = PIPELINE_PRESETS.get(pipeline_name)
    if not pipeline_fn:
        pipeline_fn = flux_uncensored

    # Override restore_face if caller specified
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


# ─── Img2Img & Inpainting ─────────────────────────────────────────────────


@app.post("/v1/generate/img2img", response_model=GenerateImageResponse)
async def generate_img2img(request: Request, body: Img2ImgRequest) -> GenerateImageResponse:
    """Image-to-image generation — repaint an existing image with a new prompt.

    Upload the source image first via /v1/generate/upload, then pass the filename.
    Denoise strength controls how much to change: 0.3 = subtle, 0.6 = moderate, 0.9 = heavy.
    """
    _verify_api_key(request)
    client = _client(request)

    if body.pipeline == "realvis-img2img":
        workflow_data = realvis_img2img(
            prompt=body.prompt,
            source_image=body.source_image,
            negative_prompt=body.negative_prompt,
            denoise_strength=body.denoise_strength,
            width=body.width,
            height=body.height,
            steps=body.steps,
            cfg=body.cfg,
            seed=body.seed,
            restore_face=body.restore_face,
        )
    else:
        workflow_data = flux_img2img(
            prompt=body.prompt,
            source_image=body.source_image,
            negative_prompt=body.negative_prompt,
            denoise_strength=body.denoise_strength,
            width=body.width,
            height=body.height,
            steps=body.steps,
            cfg=body.cfg,
            seed=body.seed,
            lora_name=body.lora_name,
            lora_strength=body.lora_strength,
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


@app.post("/v1/generate/inpaint", response_model=GenerateImageResponse)
async def generate_inpaint(request: Request, body: InpaintRequest) -> GenerateImageResponse:
    """Inpainting — repaint only the masked region of an image.

    Upload source and mask images via /v1/generate/upload first.
    Mask should be white where you want to repaint, black where you want to keep.
    """
    _verify_api_key(request)
    client = _client(request)

    workflow_data = flux_inpaint(
        prompt=body.prompt,
        source_image=body.source_image,
        mask_image=body.mask_image,
        negative_prompt=body.negative_prompt,
        denoise_strength=body.denoise_strength,
        width=body.width,
        height=body.height,
        steps=body.steps,
        cfg=body.cfg,
        seed=body.seed,
        lora_name=body.lora_name,
        lora_strength=body.lora_strength,
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


# ─── Performers ───────────────────────────────────────────────────────────


@app.get("/v1/generate/performers")
async def search_performers(
    q: str = "",
    min_rating: float = 0.0,
    favorites_only: bool = False,
    limit: int = 50,
) -> list[PerformerInfo]:
    """Search the performer database."""
    performers = _load_performers()
    results = []

    for p in performers:
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
        if favorites_only and not p.get("isFavorite", False):
            continue
        if q:
            name = (p.get("name") or "").lower()
            aliases = (p.get("aliases") or "").lower()
            if q.lower() not in name and q.lower() not in aliases:
                continue

        # Coerce field types — performers.json has mixed types:
        #   careerStart/careerEnd: int or None → str | None
        #   implants: "yes"/"no"/"unknown" → bool | None
        career_start = p.get("careerStart")
        career_end = p.get("careerEnd")
        if career_start is not None:
            career_start = str(career_start)
        if career_end is not None:
            career_end = str(career_end)

        impl_raw = str(p.get("implants", "")).lower()
        implants: bool | None = (
            True if impl_raw == "yes"
            else False if impl_raw == "no"
            else None
        )

        results.append(PerformerInfo(
            name=p.get("name", ""),
            rating=float(rating),
            height=p.get("height"),
            bust=p.get("braSize"),
            implants=implants,
            body_type=p.get("bodyType"),
            ethnicity=p.get("ethnicity"),
            nationality=p.get("nationality"),
            career_start=career_start,
            career_end=career_end,
            is_favorite=p.get("isFavorite", False),
        ))

    # Sort by rating descending
    results.sort(key=lambda x: x.rating, reverse=True)
    return results[:limit]


# ─── Auto-Generation (Drop Folder) ────────────────────────────────────────


@app.get("/v1/generate/drops")
async def list_drops() -> dict:
    """List all drop folders and their processing status."""
    return auto_gen.get_status()


@app.get("/v1/generate/drops/{name}")
async def get_drop_detail(name: str) -> dict:
    """Get details for a specific drop folder."""
    entries = auto_gen.scan_drops()
    for e in entries:
        if e.name == name:
            from dataclasses import asdict
            result = asdict(e)
            # Also include manifest if processed
            manifest_path = auto_gen.REFS_DIR / name / "manifest.json" if hasattr(auto_gen, 'REFS_DIR') else None
            from .auto_gen import REFS_DIR, OUTPUT_DIR
            manifest_path = REFS_DIR / name / "manifest.json"
            if manifest_path.exists():
                import json as _json
                result["manifest"] = _json.loads(manifest_path.read_text())
            # Include output images
            output_dir = OUTPUT_DIR / name
            if output_dir.exists():
                result["output_images"] = [f.name for f in output_dir.iterdir() if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
            return result
    raise HTTPException(status_code=404, detail=f"Drop not found: {name}")


@app.post("/v1/generate/drops/{name}/process")
async def process_drop(request: Request, name: str) -> dict:
    """Manually trigger processing of a specific drop folder."""
    _verify_api_key(request)

    from fastapi import BackgroundTasks
    import asyncio

    # Run in background so we return immediately
    asyncio.create_task(auto_gen.process_drop(name))
    return {"status": "processing", "name": name, "message": f"Processing started for '{name}'"}


@app.post("/v1/generate/drops/{name}/retry")
async def retry_drop(request: Request, name: str) -> dict:
    """Retry a failed drop by clearing error marker and reprocessing."""
    _verify_api_key(request)

    from .auto_gen import DROPS_DIR
    error_marker = DROPS_DIR / name / ".error"
    done_marker = DROPS_DIR / name / ".done"

    if error_marker.exists():
        error_marker.unlink()
    if done_marker.exists():
        done_marker.unlink()

    import asyncio
    asyncio.create_task(auto_gen.process_drop(name))
    return {"status": "retrying", "name": name}


@app.post("/v1/generate/drops/scan")
async def scan_drops_now(request: Request) -> dict:
    """Force an immediate scan and process all pending drops."""
    _verify_api_key(request)

    pending = auto_gen.get_pending()
    if not pending:
        return {"message": "No pending drops", "pending": 0}

    import asyncio
    for entry in pending:
        asyncio.create_task(auto_gen.process_drop(entry.name))

    return {
        "message": f"Processing {len(pending)} drops",
        "pending": len(pending),
        "names": [e.name for e in pending],
    }


@app.get("/v1/generate/drops/{name}/images")
async def get_drop_images(name: str) -> list[str]:
    """Get generated image URLs for a processed drop."""
    from .auto_gen import OUTPUT_DIR
    output_dir = OUTPUT_DIR / name
    if not output_dir.exists():
        return []

    # Return gateway-proxied URLs
    images = []
    for f in sorted(output_dir.iterdir()):
        if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            images.append(f"/v1/generate/drops/{name}/image/{f.name}")
    return images


@app.get("/v1/generate/drops/{name}/image/{filename}")
async def serve_drop_image(name: str, filename: str) -> StreamingResponse:
    """Serve a generated image from the output folder."""
    from .auto_gen import OUTPUT_DIR

    image_path = OUTPUT_DIR / name / filename
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    # Determine content type
    ext = image_path.suffix.lower()
    content_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    content_type = content_types.get(ext, "application/octet-stream")

    return StreamingResponse(
        open(image_path, "rb"),
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/v1/generate/drops/{name}/ref/{filename}")
async def serve_drop_ref(name: str, filename: str) -> StreamingResponse:
    """Serve a reference image from the refs folder."""
    from .auto_gen import REFS_DIR

    image_path = REFS_DIR / name / filename
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Reference image not found")

    ext = image_path.suffix.lower()
    content_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    content_type = content_types.get(ext, "application/octet-stream")

    return StreamingResponse(
        open(image_path, "rb"),
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.post("/v1/generate/preview-prompts")
async def preview_prompts(request: Request) -> dict:
    """Preview what the LLM would generate as image prompts for a subject.

    Body: { "subject": "person name", "count": 3, "context": "optional extra info" }
    """
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


# ─── LoRA Training ─────────────────────────────────────────────────────────

# In-memory training job tracker
_training_jobs: dict[str, dict] = {}


@app.post("/v1/generate/train")
async def start_training(request: Request, body: TrainLoraRequest) -> TrainingJob:
    """Start LoRA training — prepares dataset then trains.

    This triggers the prepare_dataset.py + train-lora.sh scripts on the DEV node.
    ComfyUI is stopped during training to free GPU memory.
    """
    _verify_api_key(request)

    import asyncio
    import uuid as _uuid

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
        import subprocess
        try:
            # Step 1: Prepare dataset
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

            # Step 2: Train LoRA
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
            # Poll for progress (basic — check if process is still running)
            while proc.returncode is None:
                await asyncio.sleep(5)
                try:
                    proc.poll()  # type: ignore
                except Exception:
                    pass
                # Increment progress estimate
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


@app.get("/v1/generate/train/{job_id}")
async def training_status(job_id: str) -> TrainingJob:
    """Get training job status."""
    job = _training_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Training job not found: {job_id}")
    return TrainingJob(**job)


@app.get("/v1/generate/train")
async def list_training_jobs() -> list[TrainingJob]:
    """List all training jobs."""
    return [TrainingJob(**j) for j in _training_jobs.values()]


# ─── Performer Reference Photos ───────────────────────────────────────────

PERFORMER_REFS_DIR = os.environ.get(
    "PERFORMER_REFS_DIR",
    "/mnt/vault/data/performer-refs",
)


@app.post("/v1/generate/upload-ref")
async def upload_performer_ref(request: Request) -> dict:
    """Upload a reference photo for a performer.

    Multipart form: performer_name (str) + file (image).
    Saves to VAULT at /mnt/vault/data/performer-refs/<slug>/ref_XX.jpg
    """
    _verify_api_key(request)

    from fastapi import UploadFile, Form, File
    import re

    form = await request.form()
    performer_name = form.get("performer_name", "")
    file = form.get("file")

    if not performer_name or not file:
        raise HTTPException(status_code=400, detail="performer_name and file are required")

    # Slugify performer name
    slug = re.sub(r"[^a-z0-9]+", "-", str(performer_name).lower()).strip("-")
    ref_dir = Path(PERFORMER_REFS_DIR) / slug
    ref_dir.mkdir(parents=True, exist_ok=True)

    # Find next ref number
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


@app.get("/v1/generate/performer-refs/{slug}")
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


@app.get("/v1/generate/performer-refs/{slug}/{filename}")
async def serve_performer_ref(slug: str, filename: str) -> StreamingResponse:
    """Serve a performer reference photo."""
    ref_path = Path(PERFORMER_REFS_DIR) / slug / filename
    if not ref_path.exists():
        raise HTTPException(status_code=404, detail="Reference image not found")

    ext = ref_path.suffix.lower()
    ct = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    return StreamingResponse(
        open(ref_path, "rb"),
        media_type=ct.get(ext, "application/octet-stream"),
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ─── WebSocket Progress Proxy ─────────────────────────────────────────────


@app.websocket("/v1/generate/ws")
async def generation_progress_ws(websocket: WebSocket, clientId: str = ""):
    """Proxy ComfyUI WebSocket for generation progress events.

    Connect with: ws://host:8700/v1/generate/ws?clientId=<your-id>
    Forwards progress, executing, executed, execution_cached events.
    """
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
