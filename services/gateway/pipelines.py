"""ComfyUI Pipeline Presets — builds API-format workflow dicts for each generation mode.

Each preset function takes user parameters and returns a ComfyUI API prompt dict
(the JSON body sent to POST /prompt). Users never see nodes.

Presets:
    flux-uncensored: FLUX.1 Dev FP8 + flux-uncensored LoRA
    realvis-xl:      RealVisXL V5.0 photorealistic SDXL
    flux-faceid:     FLUX.1 Dev + PuLID identity preservation
    sdxl-faceid:     RealVisXL + IPAdapter FaceID Plus V2
    face-swap:       ReActor face swap on existing image
    custom-lora:     FLUX.1 Dev + user-trained LoRA
    queen-portrait:  832x1216 character portrait with face identity
    queen-scene:     1344x768 cinematic scene with face identity
"""

from __future__ import annotations

import random
import uuid

# Default uncensored LoRA — auto-loaded when no other LoRA is specified
DEFAULT_NSFW_LORA = "flux-uncensored.safetensors"
DEFAULT_NSFW_LORA_STRENGTH = 1.0

# Face restoration defaults
DEFAULT_FACE_RESTORE_MODEL = "GFPGANv1.4.pth"


def _seed(val: int = -1) -> int:
    """Return a fixed or random seed."""
    return val if val >= 0 else random.randint(0, 2**32 - 1)


def _client_id() -> str:
    return uuid.uuid4().hex[:16]


def _add_face_restore(
    workflow: dict,
    image_node_id: str,
    save_node_id: str,
    model: str = DEFAULT_FACE_RESTORE_MODEL,
) -> None:
    """Append face restoration (GFPGAN/CodeFormer) after VAE decode.

    Uses ReActorRestoreFace for simple post-processing — no model/clip/vae needed.
    Rewires the save node to use the restored output.
    """
    workflow["fr_restore"] = {
        "class_type": "ReActorRestoreFace",
        "inputs": {
            "image": [image_node_id, 0],
            "facedetection": "retinaface_resnet50",
            "model": model,
            "visibility": 1.0,
            "codeformer_weight": 0.5,
        },
    }
    # Rewire save node to use restored image
    workflow[save_node_id]["inputs"]["images"] = ["fr_restore", 0]


# ---------------------------------------------------------------------------
# FLUX Uncensored — text-to-image with unrestricted LoRA
# ---------------------------------------------------------------------------

def flux_uncensored(
    prompt: str,
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1024,
    steps: int = 25,
    cfg: float = 1.0,
    seed: int = -1,
    lora_name: str | None = None,
    lora_strength: float = 1.0,
    batch_size: int = 1,
    restore_face: bool = False,
) -> dict:
    """Build FLUX.1 Dev FP8 workflow with uncensored LoRA.

    Auto-loads the default NSFW LoRA when no other LoRA is specified,
    ensuring unrestricted content generation.
    """
    # Auto-load uncensored LoRA if none specified
    if lora_name is None:
        lora_name = DEFAULT_NSFW_LORA
        lora_strength = DEFAULT_NSFW_LORA_STRENGTH

    s = _seed(seed)
    workflow = {
        "6": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": batch_size},
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["13", 0], "vae": ["10", 0]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "flux", "images": ["8", 0]},
        },
        "10": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "ae.safetensors"},
        },
        "11": {
            "class_type": "DualCLIPLoader",
            "inputs": {
                "clip_name1": "t5xxl_fp8_e4m3fn.safetensors",
                "clip_name2": "clip_l.safetensors",
                "type": "flux",
            },
        },
        "12": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "flux1-dev-fp8.safetensors",
                "weight_dtype": "fp8_e4m3fn",
            },
        },
        "13": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["12", 0] if not lora_name else ["20", 0],
                "positive": ["16", 0],
                "negative": ["17", 0],
                "latent_image": ["6", 0],
                "seed": s,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "16": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["11", 0]},
        },
        "17": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt or "", "clip": ["11", 0]},
        },
    }

    if lora_name:
        workflow["20"] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["12", 0],
                "clip": ["11", 0],
                "lora_name": lora_name,
                "strength_model": lora_strength,
                "strength_clip": lora_strength,
            },
        }
        # Update positive/negative to use LoRA clip
        workflow["16"]["inputs"]["clip"] = ["20", 1]
        workflow["17"]["inputs"]["clip"] = ["20", 1]

    if restore_face:
        _add_face_restore(workflow, image_node_id="8", save_node_id="9")

    return {"prompt": workflow, "client_id": _client_id()}


# ---------------------------------------------------------------------------
# RealVisXL — photorealistic SDXL
# ---------------------------------------------------------------------------

def realvis_xl(
    prompt: str,
    negative_prompt: str = "blurry, low quality, deformed, ugly, bad anatomy",
    width: int = 1024,
    height: int = 1024,
    steps: int = 30,
    cfg: float = 5.0,
    seed: int = -1,
    batch_size: int = 1,
    restore_face: bool = False,
) -> dict:
    """Build RealVisXL V5.0 SDXL workflow."""
    s = _seed(seed)
    workflow = {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "RealVisXL_V5.0.safetensors"},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": batch_size},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["4", 1]},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
                "seed": s,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "denoise": 1.0,
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "realvis", "images": ["8", 0]},
        },
    }

    if restore_face:
        _add_face_restore(workflow, image_node_id="8", save_node_id="9")

    return {"prompt": workflow, "client_id": _client_id()}


# ---------------------------------------------------------------------------
# FLUX FaceID — PuLID identity preservation
# ---------------------------------------------------------------------------

def flux_faceid(
    prompt: str,
    reference_image: str,
    negative_prompt: str = "blurry, low quality, deformed",
    identity_strength: float = 1.0,
    width: int = 1024,
    height: int = 1024,
    steps: int = 25,
    cfg: float = 1.0,
    seed: int = -1,
    restore_face: bool = True,
    lora_name: str | None = None,
    lora_strength: float = 1.0,
) -> dict:
    """Build FLUX.1 Dev + PuLID workflow for face identity preservation.

    Auto-loads uncensored LoRA for unrestricted content. Face restoration
    enabled by default for photorealistic face quality.
    """
    # Auto-load uncensored LoRA
    if lora_name is None:
        lora_name = DEFAULT_NSFW_LORA
        lora_strength = DEFAULT_NSFW_LORA_STRENGTH
    s = _seed(seed)
    workflow = {
        "10": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "ae.safetensors"},
        },
        "11": {
            "class_type": "DualCLIPLoader",
            "inputs": {
                "clip_name1": "t5xxl_fp8_e4m3fn.safetensors",
                "clip_name2": "clip_l.safetensors",
                "type": "flux",
            },
        },
        "12": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "flux1-dev-fp8.safetensors",
                "weight_dtype": "fp8_e4m3fn",
            },
        },
        # PuLID nodes
        "30": {
            "class_type": "PulidFluxModelLoader",
            "inputs": {"pulid_file": "pulid_flux_v0.9.1.safetensors"},
        },
        "31": {
            "class_type": "PulidFluxInsightFaceLoader",
            "inputs": {"provider": "CUDA"},
        },
        "32": {
            "class_type": "PulidFluxEvaClipLoader",
            "inputs": {},
        },
        "33": {
            "class_type": "LoadImage",
            "inputs": {"image": reference_image},
        },
        "34": {
            "class_type": "ApplyPulidFlux",
            "inputs": {
                "model": ["12", 0],
                "pulid_flux": ["30", 0],
                "eva_clip": ["32", 0],
                "face_analysis": ["31", 0],
                "image": ["33", 0],
                "weight": identity_strength,
                "start_at": 0.0,
                "end_at": 1.0,
                "fusion": "mean",
                "fusion_weight_max": 1.0,
                "fusion_weight_min": 0.0,
                "train_step": 1000,
                "use_gray": True,
            },
        },
        "6": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "16": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["11", 0]},
        },
        "17": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["11", 0]},
        },
        "13": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["34", 0],  # PuLID-enhanced model
                "positive": ["16", 0],
                "negative": ["17", 0],
                "latent_image": ["6", 0],
                "seed": s,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["13", 0], "vae": ["10", 0]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "faceid", "images": ["8", 0]},
        },
    }

    # Add LoRA (uncensored by default) — insert between UNET and PuLID
    if lora_name:
        workflow["20"] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["12", 0],
                "clip": ["11", 0],
                "lora_name": lora_name,
                "strength_model": lora_strength,
                "strength_clip": lora_strength,
            },
        }
        # PuLID takes model from LoRA output instead of raw UNET
        workflow["34"]["inputs"]["model"] = ["20", 0]
        # CLIP encoders use LoRA-modified clip
        workflow["16"]["inputs"]["clip"] = ["20", 1]
        workflow["17"]["inputs"]["clip"] = ["20", 1]

    if restore_face:
        _add_face_restore(workflow, image_node_id="8", save_node_id="9")

    return {"prompt": workflow, "client_id": _client_id()}


# ---------------------------------------------------------------------------
# SDXL FaceID — IPAdapter FaceID Plus V2
# ---------------------------------------------------------------------------

def sdxl_faceid(
    prompt: str,
    reference_image: str,
    negative_prompt: str = "blurry, low quality, deformed, ugly, bad anatomy",
    identity_strength: float = 1.0,
    width: int = 1024,
    height: int = 1024,
    steps: int = 30,
    cfg: float = 5.0,
    seed: int = -1,
    restore_face: bool = True,
) -> dict:
    """Build RealVisXL + IPAdapter FaceID Plus V2 workflow.

    Uses IPAdapterUnifiedLoaderFaceID for automatic model selection,
    plus the companion FaceID LoRA for best results.
    """
    s = _seed(seed)
    workflow = {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "RealVisXL_V5.0.safetensors"},
        },
        # IPAdapter unified loader — handles model + CLIP vision + InsightFace
        "41": {
            "class_type": "IPAdapterUnifiedLoaderFaceID",
            "inputs": {
                "model": ["4", 0],
                "preset": "FACEID PLUS V2",
                "lora_strength": 0.6,
                "provider": "CUDA",
            },
        },
        "42": {
            "class_type": "LoadImage",
            "inputs": {"image": reference_image},
        },
        "40": {
            "class_type": "IPAdapterFaceID",
            "inputs": {
                "model": ["41", 0],
                "ipadapter": ["41", 1],
                "image": ["42", 0],
                "weight": identity_strength,
                "weight_type": "style transfer (SDXL)",
                "start_at": 0.0,
                "end_at": 1.0,
            },
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["4", 1]},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["40", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
                "seed": s,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "denoise": 1.0,
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "faceid_sdxl", "images": ["8", 0]},
        },
    }

    if restore_face:
        _add_face_restore(workflow, image_node_id="8", save_node_id="9")

    return {"prompt": workflow, "client_id": _client_id()}


# ---------------------------------------------------------------------------
# Face Swap — ReActor post-processing
# ---------------------------------------------------------------------------

def face_swap(
    source_image: str,
    face_image: str,
    restore_face: bool = True,
) -> dict:
    """Build ReActor face swap workflow."""
    workflow = {
        "1": {
            "class_type": "LoadImage",
            "inputs": {"image": source_image},
        },
        "2": {
            "class_type": "LoadImage",
            "inputs": {"image": face_image},
        },
        "3": {
            "class_type": "ReActorFaceSwap",
            "inputs": {
                "input_image": ["1", 0],
                "source_image": ["2", 0],
                "swap_model": "inswapper_128.onnx",
                "facedetection": "retinaface_resnet50",
                "face_restore_model": "GFPGANv1.4.pth" if restore_face else "none",
                "face_restore_visibility": 1.0,
                "codeformer_weight": 0.5,
                "console_log_level": 1,
            },
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "swap", "images": ["3", 0]},
        },
    }
    return {"prompt": workflow, "client_id": _client_id()}


# ---------------------------------------------------------------------------
# Queen Portrait — 832x1216 character portrait
# ---------------------------------------------------------------------------

def queen_portrait(
    prompt: str,
    reference_image: str | None = None,
    lora_name: str | None = None,
    identity_strength: float = 1.0,
    seed: int = -1,
    negative_prompt: str = "blurry, low quality, deformed, ugly, bad anatomy",
    restore_face: bool = True,
) -> dict:
    """Build queen portrait workflow (832x1216).

    Uses PuLID if reference_image provided, or LoRA if trained, or basic FLUX.
    Face restoration enabled by default for character consistency.
    """
    if reference_image:
        return flux_faceid(
            prompt=prompt,
            reference_image=reference_image,
            negative_prompt=negative_prompt,
            identity_strength=identity_strength,
            width=832,
            height=1216,
            steps=25,
            cfg=1.0,
            seed=seed,
            restore_face=restore_face,
            lora_name=lora_name,
        )
    else:
        return flux_uncensored(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=832,
            height=1216,
            steps=25,
            cfg=1.0,
            seed=seed,
            lora_name=lora_name,
            lora_strength=1.0,
            restore_face=restore_face,
        )


# ---------------------------------------------------------------------------
# Queen Scene — 1344x768 cinematic widescreen
# ---------------------------------------------------------------------------

def queen_scene(
    prompt: str,
    reference_image: str | None = None,
    lora_name: str | None = None,
    identity_strength: float = 1.0,
    seed: int = -1,
    negative_prompt: str = "blurry, low quality, deformed, ugly, bad anatomy",
    restore_face: bool = True,
) -> dict:
    """Build queen scene workflow (1344x768 cinematic).

    Uses PuLID if reference_image provided, or LoRA if trained, or basic FLUX.
    Face restoration enabled by default for character consistency.
    """
    if reference_image:
        return flux_faceid(
            prompt=prompt,
            reference_image=reference_image,
            negative_prompt=negative_prompt,
            identity_strength=identity_strength,
            width=1344,
            height=768,
            steps=25,
            cfg=1.0,
            seed=seed,
            restore_face=restore_face,
            lora_name=lora_name,
        )
    else:
        return flux_uncensored(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=1344,
            height=768,
            steps=25,
            cfg=1.0,
            seed=seed,
            lora_name=lora_name,
            lora_strength=1.0,
            restore_face=restore_face,
        )


# ---------------------------------------------------------------------------
# Preset Registry
# ---------------------------------------------------------------------------

PIPELINE_PRESETS = {
    "flux-uncensored": flux_uncensored,
    "realvis-xl": realvis_xl,
    "flux-faceid": flux_faceid,
    "sdxl-faceid": sdxl_faceid,
    "face-swap": face_swap,
    "queen-portrait": queen_portrait,
    "queen-scene": queen_scene,
}
