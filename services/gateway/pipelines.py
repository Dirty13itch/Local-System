"""ComfyUI Pipeline Presets — builds API-format workflow dicts for each generation mode.

Each preset function takes user parameters and returns a ComfyUI API prompt dict
(the JSON body sent to POST /prompt). Users never see nodes.

Presets:
    flux-uncensored:   FLUX.1 Dev FP8 + flux-uncensored LoRA
    realvis-xl:        RealVisXL V5.0 photorealistic SDXL
    flux-faceid:       FLUX.1 Dev + PuLID identity preservation
    flux-infiniteyou:  FLUX.1 Dev + InfiniteYou (ByteDance) identity
    sdxl-faceid:       RealVisXL + IPAdapter FaceID Plus V2
    face-swap:         ReActor face swap on existing image
    custom-lora:       FLUX.1 Dev + user-trained LoRA
    queen-portrait:    832x1216 character portrait with face identity
    queen-scene:       1344x768 cinematic scene with face identity
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


# Default FaceDetailer settings
DEFAULT_FD_GUIDE_SIZE = 480
DEFAULT_FD_MAX_SIZE = 1024
DEFAULT_FD_DENOISE = 0.4  # Subtle refinement — preserves identity
DEFAULT_FD_STEPS = 20
DEFAULT_FD_CFG = 1.0  # Match FLUX cfg

# Face detection model for Impact-Pack
DEFAULT_FACE_DETECT_MODEL = "face_yolov8m.pt"
DEFAULT_SAM_MODEL = "sam_vit_b_01ec64.pth"

# Upscaler model
DEFAULT_UPSCALER_MODEL = "4x-UltraSharp.pth"


def _add_face_detailer(
    workflow: dict,
    image_node_id: str,
    model_node_id: str,
    clip_node_id: str,
    vae_node_id: str,
    pos_cond_node_id: str,
    neg_cond_node_id: str,
    save_node_id: str,
    model_output_slot: int = 0,
    clip_output_slot: int = 0,
    denoise: float = DEFAULT_FD_DENOISE,
    steps: int = DEFAULT_FD_STEPS,
    cfg: float = DEFAULT_FD_CFG,
    guide_size: int = DEFAULT_FD_GUIDE_SIZE,
    seed: int = -1,
) -> None:
    """Add FaceDetailer post-processing (Impact-Pack) after generation.

    Detects face regions via YOLOv8, creates precise masks with SAM,
    then inpaints face regions at higher detail using the same model/prompt.
    Much better than simple GFPGAN restore for preserving identity while
    enhancing face quality.

    The model/clip output slots allow flexibility — e.g. LoraLoader outputs
    clip on slot 1, while DualCLIPLoader outputs on slot 0.

    Requires on WORKSHOP: ComfyUI-Impact-Pack, face_yolov8m.pt, sam_vit_b.
    """
    s = _seed(seed)

    # BBOX face detector (YOLOv8)
    workflow["fd_detector"] = {
        "class_type": "UltralyticsDetectorProvider",
        "inputs": {"model_name": DEFAULT_FACE_DETECT_MODEL},
    }

    # SAM model for precise face masking
    workflow["fd_sam"] = {
        "class_type": "SAMLoader",
        "inputs": {
            "model_name": DEFAULT_SAM_MODEL,
            "device_mode": "AUTO",
        },
    }

    # FaceDetailer node — the core enhancement
    workflow["fd_main"] = {
        "class_type": "FaceDetailer",
        "inputs": {
            "image": [image_node_id, 0],
            "model": [model_node_id, model_output_slot],
            "clip": [clip_node_id, clip_output_slot],
            "vae": [vae_node_id, 0],
            "positive": [pos_cond_node_id, 0],
            "negative": [neg_cond_node_id, 0],
            "bbox_detector": ["fd_detector", 0],
            "sam_model_opt": ["fd_sam", 0],
            "segm_detector_opt": None,
            "detailer_hook": None,
            "guide_size": guide_size,
            "guide_size_for": True,  # guide_size_for_bbox
            "max_size": DEFAULT_FD_MAX_SIZE,
            "seed": s,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": "euler",
            "scheduler": "simple",
            "denoise": denoise,
            "feather": 10,
            "noise_mask": True,
            "force_inpaint": False,
            "bbox_threshold": 0.5,
            "bbox_dilation": 10,
            "bbox_crop_factor": 3.0,
            "sam_detection_hint": "center-1",
            "sam_dilation": 10,
            "sam_threshold": 0.93,
            "sam_bbox_expansion": 0,
            "sam_mask_hint_threshold": 0.7,
            "sam_mask_hint_use_negative": "False",
            "drop_size": 10,
            "cycle": 1,
            "inpaint_model": False,
            "noise_mask_feather": 20,
        },
    }

    # Rewire save node to use FaceDetailer output
    workflow[save_node_id]["inputs"]["images"] = ["fd_main", 0]


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
    face_detailer: bool = False,
    lora_name: str | None = None,
    lora_strength: float = 1.0,
) -> dict:
    """Build FLUX.1 Dev + PuLID workflow for face identity preservation.

    Auto-loads uncensored LoRA for unrestricted content.

    Post-processing options (mutually exclusive — face_detailer takes priority):
      face_detailer: Impact-Pack FaceDetailer (YOLOv8 detect → SAM mask → inpaint).
                     Higher quality but requires Impact-Pack + models on WORKSHOP.
      restore_face: ReActor GFPGAN face restore (simpler, faster, always available).
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

    if face_detailer:
        # FaceDetailer: YOLOv8 face detection → SAM masking → re-inpaint face
        # Model always comes from PuLID output ("34") regardless of LoRA
        # CLIP depends on whether LoRA is active (slot 1) or raw (slot 0)
        _add_face_detailer(
            workflow,
            image_node_id="8",
            model_node_id="34",
            clip_node_id="20" if lora_name else "11",
            vae_node_id="10",
            pos_cond_node_id="16",
            neg_cond_node_id="17",
            save_node_id="9",
            clip_output_slot=1 if lora_name else 0,
            seed=s,
        )
    elif restore_face:
        _add_face_restore(workflow, image_node_id="8", save_node_id="9")

    return {"prompt": workflow, "client_id": _client_id()}


# ---------------------------------------------------------------------------
# FLUX InfiniteYou — ControlNet-like identity preservation (ByteDance)
# ---------------------------------------------------------------------------

# InfiniteYou model variants
INFINITEYOU_SIM = "sim_stage1"  # Higher identity similarity
INFINITEYOU_AES = "aes_stage2"  # Better aesthetics

# Default InfiniteYou settings
DEFAULT_IY_STRENGTH = 0.85
DEFAULT_IY_NUM_TOKENS = 8  # Token count must match image_proj_model architecture


def flux_infiniteyou(
    prompt: str,
    reference_image: str,
    negative_prompt: str = "blurry, low quality, deformed",
    identity_strength: float = DEFAULT_IY_STRENGTH,
    width: int = 1024,
    height: int = 1024,
    steps: int = 25,
    cfg: float = 1.0,
    seed: int = -1,
    restore_face: bool = True,
    face_detailer: bool = False,
    lora_name: str | None = None,
    lora_strength: float = 1.0,
    variant: str = INFINITEYOU_SIM,
    num_tokens: int = DEFAULT_IY_NUM_TOKENS,
) -> dict:
    """Build FLUX.1 Dev + InfiniteYou (ByteDance) identity preservation workflow.

    InfiniteYou uses InfuseNet (ControlNet-like) with face embeddings injected
    into conditioning — eliminates face copy-paste artifacts common in PuLID.

    Variants:
      sim_stage1: Higher identity similarity (default, best for digital replicas)
      aes_stage2: Better overall aesthetics (slight identity trade-off)

    Post-processing (mutually exclusive — face_detailer takes priority):
      face_detailer: Impact-Pack FaceDetailer (YOLOv8 → SAM → inpaint).
      restore_face: ReActor GFPGAN face restore (simpler, faster).
    """
    # Auto-load uncensored LoRA
    if lora_name is None:
        lora_name = DEFAULT_NSFW_LORA
        lora_strength = DEFAULT_NSFW_LORA_STRENGTH

    s = _seed(seed)

    # Determine model file names based on variant
    image_proj_name = f"{variant}/image_proj_model.bin"
    infusenet_name = f"{variant}/infusenet_{'sim' if variant == INFINITEYOU_SIM else 'aes'}_fp8e4m3fn.safetensors"

    workflow = {
        # ── Model loading ───────────────────────────────────
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
        # ── LoRA (uncensored) ───────────────────────────────
        "20": {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["12", 0],
                "clip": ["11", 0],
                "lora_name": lora_name,
                "strength_model": lora_strength,
                "strength_clip": lora_strength,
            },
        },
        # ── Prompt encoding ─────────────────────────────────
        "16": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": prompt,
                "clip": ["20", 1],  # clip from LoRA
            },
        },
        "17": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": negative_prompt,
                "clip": ["20", 1],
            },
        },
        # ── Reference image ─────────────────────────────────
        "15": {
            "class_type": "LoadImage",
            "inputs": {"image": reference_image},
        },
        # ── InfiniteYou identity pipeline ───────────────────
        # Load face detector + arcface + image_proj models
        "30": {
            "class_type": "IDEmbeddingModelLoader",
            "inputs": {
                "image_proj_model_name": image_proj_name,
                "image_proj_num_tokens": num_tokens,
                "face_analysis_provider": "CUDA",
                "face_analysis_det_size": "AUTO",
            },
        },
        # Extract face identity embedding from reference image
        "31": {
            "class_type": "ExtractIDEmbedding",
            "inputs": {
                "face_detector": ["30", 0],
                "arcface_model": ["30", 1],
                "image_proj_model": ["30", 2],
                "image": ["15", 0],
            },
        },
        # Load InfuseNet ControlNet model
        "32": {
            "class_type": "InfuseNetLoader",
            "inputs": {
                "controlnet_name": infusenet_name,
            },
        },
        # Apply InfuseNet — injects identity into conditioning
        "33": {
            "class_type": "InfuseNetApply",
            "inputs": {
                "positive": ["16", 0],
                "id_embedding": ["31", 0],
                "control_net": ["32", 0],
                "image": ["15", 0],
                "strength": identity_strength,
                "start_percent": 0.0,
                "end_percent": 1.0,
                "negative": ["17", 0],
                "vae": ["10", 0],
            },
        },
        # ── Empty latent ────────────────────────────────────
        "13": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {
                "width": width,
                "height": height,
                "batch_size": 1,
            },
        },
        # ── Sampling ────────────────────────────────────────
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["20", 0],  # model from LoRA (InfiniteYou modifies conditioning, not model)
                "positive": ["33", 0],  # InfuseNet-modified positive
                "negative": ["33", 1],  # InfuseNet-modified negative
                "latent_image": ["13", 0],
                "seed": s,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        # ── Decode + save ───────────────────────────────────
        "8": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["6", 0],
                "vae": ["10", 0],
            },
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["8", 0],
                "filename_prefix": "infiniteyou",
            },
        },
    }

    # ── Post-processing ─────────────────────────────────────
    if face_detailer:
        _add_face_detailer(
            workflow,
            image_node_id="8",
            model_node_id="20",  # model from LoRA (InfiniteYou doesn't modify model)
            clip_node_id="20",
            vae_node_id="10",
            pos_cond_node_id="16",
            neg_cond_node_id="17",
            save_node_id="9",
            clip_output_slot=1,
            seed=s,
        )
    elif restore_face:
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
    face_detailer: bool = False,
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
            face_detailer=face_detailer,
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
    face_detailer: bool = False,
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
            face_detailer=face_detailer,
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
# FLUX Img2Img — image-to-image with uncensored LoRA
# ---------------------------------------------------------------------------

def flux_img2img(
    prompt: str,
    source_image: str,
    negative_prompt: str = "",
    denoise_strength: float = 0.6,
    width: int = 1024,
    height: int = 1024,
    steps: int = 25,
    cfg: float = 1.0,
    seed: int = -1,
    lora_name: str | None = None,
    lora_strength: float = 1.0,
    restore_face: bool = False,
) -> dict:
    """Build FLUX.1 Dev img2img workflow.

    Takes an existing image and re-renders it with the given prompt at the
    specified denoise strength (0.0 = keep original, 1.0 = full redraw).
    Auto-loads uncensored LoRA.
    """
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
        # Load source image
        "50": {
            "class_type": "LoadImage",
            "inputs": {"image": source_image},
        },
        # Resize to target dimensions
        "51": {
            "class_type": "Image Resize",
            "inputs": {
                "image": ["50", 0],
                "mode": "resize",
                "supersample": "true",
                "resampling": "lanczos",
                "rescale_factor": 1,
                "resize_width": width,
                "resize_height": height,
            },
        },
        # Encode source image to latent
        "52": {
            "class_type": "VAEEncode",
            "inputs": {
                "pixels": ["51", 0],
                "vae": ["10", 0],
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
        "13": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["12", 0],
                "positive": ["16", 0],
                "negative": ["17", 0],
                "latent_image": ["52", 0],  # Encoded source image
                "seed": s,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": denoise_strength,
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["13", 0], "vae": ["10", 0]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "img2img", "images": ["8", 0]},
        },
    }

    # Add LoRA
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
        workflow["13"]["inputs"]["model"] = ["20", 0]
        workflow["16"]["inputs"]["clip"] = ["20", 1]
        workflow["17"]["inputs"]["clip"] = ["20", 1]

    if restore_face:
        _add_face_restore(workflow, image_node_id="8", save_node_id="9")

    return {"prompt": workflow, "client_id": _client_id()}


# ---------------------------------------------------------------------------
# RealVisXL Img2Img
# ---------------------------------------------------------------------------

def realvis_img2img(
    prompt: str,
    source_image: str,
    negative_prompt: str = "blurry, low quality, deformed, ugly, bad anatomy",
    denoise_strength: float = 0.6,
    width: int = 1024,
    height: int = 1024,
    steps: int = 30,
    cfg: float = 5.0,
    seed: int = -1,
    restore_face: bool = False,
) -> dict:
    """Build RealVisXL V5.0 img2img workflow."""
    s = _seed(seed)
    workflow = {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "RealVisXL_V5.0.safetensors"},
        },
        "50": {
            "class_type": "LoadImage",
            "inputs": {"image": source_image},
        },
        "51": {
            "class_type": "Image Resize",
            "inputs": {
                "image": ["50", 0],
                "mode": "resize",
                "supersample": "true",
                "resampling": "lanczos",
                "rescale_factor": 1,
                "resize_width": width,
                "resize_height": height,
            },
        },
        "52": {
            "class_type": "VAEEncode",
            "inputs": {
                "pixels": ["51", 0],
                "vae": ["4", 2],
            },
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
                "latent_image": ["52", 0],
                "seed": s,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "denoise": denoise_strength,
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "img2img_realvis", "images": ["8", 0]},
        },
    }

    if restore_face:
        _add_face_restore(workflow, image_node_id="8", save_node_id="9")

    return {"prompt": workflow, "client_id": _client_id()}


# ---------------------------------------------------------------------------
# FLUX Inpaint — masked region repaint with uncensored LoRA
# ---------------------------------------------------------------------------

def flux_inpaint(
    prompt: str,
    source_image: str,
    mask_image: str,
    negative_prompt: str = "",
    denoise_strength: float = 0.8,
    width: int = 1024,
    height: int = 1024,
    steps: int = 25,
    cfg: float = 1.0,
    seed: int = -1,
    lora_name: str | None = None,
    lora_strength: float = 1.0,
    restore_face: bool = False,
) -> dict:
    """Build FLUX.1 Dev inpainting workflow.

    Repaints only the masked region (white=repaint, black=keep) of the source
    image using the given prompt. Auto-loads uncensored LoRA.
    """
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
        # Source image
        "50": {
            "class_type": "LoadImage",
            "inputs": {"image": source_image},
        },
        "51": {
            "class_type": "Image Resize",
            "inputs": {
                "image": ["50", 0],
                "mode": "resize",
                "supersample": "true",
                "resampling": "lanczos",
                "rescale_factor": 1,
                "resize_width": width,
                "resize_height": height,
            },
        },
        # Mask image (white = repaint, black = keep)
        "55": {
            "class_type": "LoadImage",
            "inputs": {"image": mask_image},
        },
        "56": {
            "class_type": "ImageToMask",
            "inputs": {
                "image": ["55", 0],
                "channel": "red",
            },
        },
        # Encode to latent
        "52": {
            "class_type": "VAEEncode",
            "inputs": {
                "pixels": ["51", 0],
                "vae": ["10", 0],
            },
        },
        # Apply mask to latent
        "53": {
            "class_type": "SetLatentNoiseMask",
            "inputs": {
                "samples": ["52", 0],
                "mask": ["56", 0],
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
        "13": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["12", 0],
                "positive": ["16", 0],
                "negative": ["17", 0],
                "latent_image": ["53", 0],  # Masked latent
                "seed": s,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": denoise_strength,
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["13", 0], "vae": ["10", 0]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "inpaint", "images": ["8", 0]},
        },
    }

    # Add LoRA
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
        workflow["13"]["inputs"]["model"] = ["20", 0]
        workflow["16"]["inputs"]["clip"] = ["20", 1]
        workflow["17"]["inputs"]["clip"] = ["20", 1]

    if restore_face:
        _add_face_restore(workflow, image_node_id="8", save_node_id="9")

    return {"prompt": workflow, "client_id": _client_id()}


# ---------------------------------------------------------------------------
# Preset Registry
# ---------------------------------------------------------------------------

PIPELINE_PRESETS = {
    "flux-uncensored": flux_uncensored,
    "realvis-xl": realvis_xl,
    "flux-faceid": flux_faceid,
    "flux-infiniteyou": flux_infiniteyou,
    "sdxl-faceid": sdxl_faceid,
    "face-swap": face_swap,
    "queen-portrait": queen_portrait,
    "queen-scene": queen_scene,
    "flux-img2img": flux_img2img,
    "realvis-img2img": realvis_img2img,
    "flux-inpaint": flux_inpaint,
}
