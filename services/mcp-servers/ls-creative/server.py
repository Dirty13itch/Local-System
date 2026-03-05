"""ls-creative — Image generation & creative tools MCP server.

Gives any MCP-capable coding tool access to ComfyUI image generation
through the Gateway service. Supports pipeline presets, queen portraits,
face generation, and img2img workflows.

Routes to:
  Gateway (DEV:8700) → ComfyUI (WORKSHOP:8188)

Framework: FastMCP 2.0
Transport: stdio (over SSH from DESK/DEV)
"""

from __future__ import annotations

import os

import httpx
from fastmcp import FastMCP

# --- Configuration ---

DEV_HOST = os.environ.get("DEV_HOST", "192.168.1.189")
GATEWAY_PORT = int(os.environ.get("GATEWAY_PORT", "8700"))
GATEWAY_URL = f"http://{DEV_HOST}:{GATEWAY_PORT}"
API_KEY = os.environ.get("GATEWAY_API_KEY", "sk-athanor-gateway-2026")
REQUEST_TIMEOUT = float(os.environ.get("CREATIVE_TIMEOUT", "120"))

_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(REQUEST_TIMEOUT),
            headers={
                "Content-Type": "application/json",
                "X-API-Key": API_KEY,
            },
        )
    return _client


# --- MCP Server ---

mcp = FastMCP(
    "ls-creative",
    instructions=(
        "Generate images using ComfyUI on the local cluster. "
        "Supports FLUX pipelines, face-identity generation, img2img, "
        "queen portraits, and more. All generation is free and local."
    ),
)


@mcp.tool()
async def generate_image(
    prompt: str,
    pipeline: str = "flux-default",
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1024,
    seed: int = -1,
    steps: int | None = None,
) -> dict:
    """Generate an image using ComfyUI with a FLUX pipeline.

    All generation runs locally on the cluster GPU — free and private.

    Args:
        prompt: Text description of the image to generate
        pipeline: Pipeline preset name (use list_pipelines to see options)
        negative_prompt: What to avoid in the image
        width: Image width in pixels (default: 1024)
        height: Image height in pixels (default: 1024)
        seed: Random seed (-1 for random)
        steps: Number of inference steps (default: pipeline-specific)
    """
    client = await get_client()
    body: dict = {
        "prompt": prompt,
        "pipeline": pipeline,
        "negative_prompt": negative_prompt,
        "width": width,
        "height": height,
        "seed": seed,
    }
    if steps is not None:
        body["steps"] = steps

    try:
        resp = await client.post(f"{GATEWAY_URL}/v1/generate", json=body)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text[:500]}"}
    except Exception as e:
        return {"error": f"Generation failed: {e}"}


@mcp.tool()
async def generate_face(
    prompt: str,
    reference_image: str,
    pipeline: str = "flux-faceid",
    identity_strength: float = 0.8,
    seed: int = -1,
) -> dict:
    """Generate an image with face identity from a reference photo.

    Uses FLUX FaceID pipeline to maintain facial identity while
    generating new poses, scenes, and styles.

    Args:
        prompt: Description of the desired image
        reference_image: Path to reference face image (on cluster filesystem)
        pipeline: Face pipeline to use (default: "flux-faceid")
        identity_strength: How closely to match the reference face (0.0-1.0)
        seed: Random seed (-1 for random)
    """
    client = await get_client()
    try:
        resp = await client.post(
            f"{GATEWAY_URL}/v1/generate/face",
            json={
                "prompt": prompt,
                "reference_image": reference_image,
                "pipeline": pipeline,
                "identity_strength": identity_strength,
                "seed": seed,
            },
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": f"Face generation failed: {e}"}


@mcp.tool()
async def generate_queen(
    queen_id: str,
    mode: str = "portrait",
    scene_index: int | None = None,
    identity_strength: float = 0.8,
    seed: int = -1,
    prompt_override: str | None = None,
) -> dict:
    """Generate an EoBQ queen portrait or scene with face identity.

    Uses the queen's physical blueprint, DNA modifiers, and scene
    descriptions from the Master Document to build prompts automatically.

    Args:
        queen_id: Queen identifier (e.g., "aurora", "seraphina")
        mode: "portrait" for headshot, "scene" for full scene
        scene_index: Scene number for scene mode (from queen's scene list)
        identity_strength: Face identity strength (0.0-1.0)
        seed: Random seed (-1 for random)
        prompt_override: Override the auto-generated prompt entirely
    """
    client = await get_client()
    body: dict = {
        "queen_id": queen_id,
        "mode": mode,
        "identity_strength": identity_strength,
        "seed": seed,
    }
    if scene_index is not None:
        body["scene_index"] = scene_index
    if prompt_override:
        body["prompt_override"] = prompt_override

    try:
        resp = await client.post(f"{GATEWAY_URL}/v1/generate/queen", json=body)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": f"Queen generation failed: {e}"}


@mcp.tool()
async def list_pipelines() -> list[dict]:
    """List all available ComfyUI generation pipelines.

    Shows pipeline names, descriptions, and default settings.
    """
    client = await get_client()
    try:
        resp = await client.get(f"{GATEWAY_URL}/v1/generate/pipelines")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return [{"error": f"Failed to list pipelines: {e}"}]


@mcp.tool()
async def list_queens() -> list[dict]:
    """List all EoBQ queen profiles with their details."""
    client = await get_client()
    try:
        resp = await client.get(f"{GATEWAY_URL}/v1/generate/queens")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return [{"error": f"Failed to list queens: {e}"}]


@mcp.tool()
async def generation_status(prompt_id: str) -> dict:
    """Check the status of an image generation job.

    Args:
        prompt_id: The prompt ID returned from a generate call
    """
    client = await get_client()
    try:
        resp = await client.get(f"{GATEWAY_URL}/v1/generate/status/{prompt_id}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": f"Status check failed: {e}"}


@mcp.tool()
async def list_comfyui_models() -> dict:
    """List models available in ComfyUI (checkpoints, LoRAs, etc.)."""
    client = await get_client()
    try:
        resp = await client.get(f"{GATEWAY_URL}/v1/generate/models")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": f"Failed to list models: {e}"}


@mcp.tool()
async def generation_history(limit: int = 10) -> list[dict]:
    """Get recent generation history with prompts and outputs.

    Args:
        limit: Maximum entries to return (default: 10)
    """
    client = await get_client()
    try:
        resp = await client.get(
            f"{GATEWAY_URL}/v1/generate/history",
            params={"limit": limit},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return [{"error": f"Failed to get history: {e}"}]


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
