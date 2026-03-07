#!/usr/bin/env python3
"""Automated LoRA training pipeline for subject identity preservation.

Trains a Flux LoRA on curated images to capture face + body + skin + tattoo
identity features. Wraps Kohya_ss sd-scripts for training.

Training directory layout:
    /mnt/vault/data/gen-subjects/{slug}/
      ├── ref_01.jpg ... ref_10.jpg           ← face-ID references (Tier 1)
      ├── training/
      │   ├── 50_sks_{slug}/                  ← training images (50 repeats)
      │   │   ├── img_001.jpg ... img_050.jpg
      │   │   └── img_001.txt ... img_050.txt ← captions (auto-generated)
      │   └── config.toml                     ← Kohya training config
      └── loras/
          ├── {slug}_v1.safetensors           ← trained LoRA output
          └── {slug}_v1_metadata.json         ← training params, metrics

Requirements:
    - Kohya_ss / sd-scripts installed on FOUNDRY
    - CUDA GPU (RTX 5090 ideal, RTX 5070 Ti works)
    - Training images prepared via extract_face_refs.py --mode train

Runs on FOUNDRY GPU 4 (spare RTX 5070 Ti).

Usage:
    python scripts/train_subject_lora.py --subject peta-jensen
    python scripts/train_subject_lora.py --subject peta-jensen --gpu 4 --rank 64
    python scripts/train_subject_lora.py --subject peta-jensen --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_lora")


# ─── Config ──────────────────────────────────────────────────────────────

SUBJECTS_DIR = Path(os.environ.get("GEN_SUBJECTS_DIR", "/mnt/vault/data/gen-subjects"))
KOHYA_DIR = Path(os.environ.get("KOHYA_DIR", "/opt/kohya_ss"))

# Training defaults (optimized for identity preservation)
DEFAULT_CONFIG = {
    "pretrained_model_name_or_path": "black-forest-labs/FLUX.1-dev",
    "network_module": "networks.lora_flux",
    "network_dim": 64,           # rank — higher = more identity detail
    "network_alpha": 32,         # alpha = dim/2 is standard
    "learning_rate": 0.0008,
    "unet_lr": 0.0008,
    "text_encoder_lr": 0.00005,
    "lr_scheduler": "cosine_with_restarts",
    "lr_warmup_steps": 100,
    "optimizer_type": "AdamW8bit",
    "max_train_steps": 2000,
    "train_batch_size": 1,
    "resolution": "1024,1024",
    "mixed_precision": "bf16",
    "save_precision": "bf16",
    "gradient_checkpointing": True,
    "gradient_accumulation_steps": 1,
    "cache_latents": True,
    "cache_latents_to_disk": True,
    "max_data_loader_n_workers": 2,
    "seed": 42,
    "save_every_n_steps": 500,
    "sample_every_n_steps": 500,
    "flip_aug": False,           # CRITICAL: disable for asymmetric tattoos
    "bucket_reso_steps": 64,
    "min_bucket_reso": 512,
    "max_bucket_reso": 1536,
    "xformers": True,
    "prior_loss_weight": 1.0,
}


# ─── Training Config Generator ──────────────────────────────────────────

def generate_training_config(
    subject_slug: str,
    training_dir: Path,
    output_dir: Path,
    trigger_word: str,
    config_overrides: dict | None = None,
) -> dict:
    """Generate a Kohya-compatible training config."""
    config = DEFAULT_CONFIG.copy()
    if config_overrides:
        config.update(config_overrides)

    # Subject-specific paths
    config["train_data_dir"] = str(training_dir)
    config["output_dir"] = str(output_dir)
    config["output_name"] = f"{subject_slug}_v1"
    config["logging_dir"] = str(output_dir / "logs")

    # Sample prompts for progress monitoring
    config["sample_prompts"] = (
        f"portrait of {trigger_word}, professional photo, "
        f"dramatic lighting, sharp focus, RAW photo --n low quality, blurry"
    )

    return config


def write_toml_config(config: dict, path: Path) -> None:
    """Write training config as TOML (Kohya format)."""
    lines = []
    for k, v in config.items():
        if isinstance(v, bool):
            lines.append(f'{k} = {"true" if v else "false"}')
        elif isinstance(v, (int, float)):
            lines.append(f"{k} = {v}")
        elif isinstance(v, str):
            lines.append(f'{k} = "{v}"')
        elif isinstance(v, list):
            items = ", ".join(f'"{i}"' if isinstance(i, str) else str(i) for i in v)
            lines.append(f"{k} = [{items}]")

    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Training config written to %s", path)


# ─── Auto-Captioning ────────────────────────────────────────────────────

def auto_caption_images(training_dir: Path, trigger_word: str) -> int:
    """Generate basic captions for training images.

    Creates {image_name}.txt files with trigger word + basic description.
    For better results, use BLIP2 or WD14 tagger.
    """
    # Find the repeats directory (e.g., 50_sks_petajensen/)
    image_dirs = [d for d in training_dir.iterdir() if d.is_dir() and d.name.startswith(("50_", "30_", "20_"))]
    if not image_dirs:
        # Try the training dir itself
        image_dirs = [training_dir]

    captioned = 0
    for img_dir in image_dirs:
        images = [
            f for f in img_dir.iterdir()
            if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        ]
        for img in images:
            caption_file = img.with_suffix(".txt")
            if caption_file.exists():
                continue

            # Basic caption with trigger word
            caption = f"{trigger_word}, high quality photo, professional lighting, sharp focus"
            caption_file.write_text(caption, encoding="utf-8")
            captioned += 1

    logger.info("Auto-captioned %d images with trigger word '%s'", captioned, trigger_word)
    return captioned


# ─── Training Execution ─────────────────────────────────────────────────

def run_training(
    config_path: Path,
    gpu_id: int = 4,
    dry_run: bool = False,
) -> dict:
    """Execute LoRA training via Kohya sd-scripts."""

    train_script = KOHYA_DIR / "flux_train_network.py"
    if not train_script.exists():
        # Try alternate locations
        alt_paths = [
            KOHYA_DIR / "sd-scripts" / "flux_train_network.py",
            Path("/opt/sd-scripts/flux_train_network.py"),
            Path.home() / "kohya_ss" / "flux_train_network.py",
        ]
        for alt in alt_paths:
            if alt.exists():
                train_script = alt
                break
        else:
            return {
                "status": "error",
                "error": f"Kohya training script not found. Checked: {KOHYA_DIR}, /opt/sd-scripts/",
            }

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)

    cmd = [
        sys.executable, str(train_script),
        "--config_file", str(config_path),
    ]

    if dry_run:
        logger.info("DRY RUN — would execute: %s", " ".join(cmd))
        logger.info("GPU: %d", gpu_id)
        return {"status": "dry_run", "command": " ".join(cmd)}

    logger.info("Starting LoRA training on GPU %d...", gpu_id)
    logger.info("Command: %s", " ".join(cmd))

    start_time = time.time()

    try:
        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=7200,  # 2 hour timeout
        )

        duration = time.time() - start_time

        if proc.returncode == 0:
            logger.info("Training completed in %.1f minutes", duration / 60)
            return {
                "status": "success",
                "duration_seconds": int(duration),
                "stdout_tail": proc.stdout[-500:] if proc.stdout else "",
            }
        else:
            logger.error("Training failed (exit code %d)", proc.returncode)
            return {
                "status": "failed",
                "exit_code": proc.returncode,
                "stderr_tail": proc.stderr[-1000:] if proc.stderr else "",
            }

    except subprocess.TimeoutExpired:
        return {"status": "timeout", "error": "Training exceeded 2-hour timeout"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─── Main Pipeline ───────────────────────────────────────────────────────

def train_subject_lora(
    subject_slug: str,
    gpu_id: int = 4,
    rank: int = 64,
    steps: int = 2000,
    learning_rate: float = 0.0008,
    trigger_word: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Full training pipeline for a subject.

    1. Validate training images exist
    2. Auto-caption if needed
    3. Generate training config
    4. Execute training
    5. Save metadata
    """
    subject_dir = SUBJECTS_DIR / subject_slug
    training_dir = subject_dir / "training"
    lora_dir = subject_dir / "loras"

    if not trigger_word:
        trigger_word = f"sks_{subject_slug.replace('-', '')}"

    result = {
        "subject": subject_slug,
        "trigger_word": trigger_word,
        "status": "pending",
    }

    # 1. Validate training images
    image_count = 0
    if training_dir.exists():
        for d in training_dir.rglob("*"):
            if d.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                image_count += 1

    if image_count < 10:
        result["status"] = "insufficient_images"
        result["error"] = (
            f"Found {image_count} training images — need at least 10 (30-50 recommended). "
            f"Run: python scripts/extract_face_refs.py --performers '{subject_slug}' --mode train"
        )
        logger.error(result["error"])
        return result

    logger.info("Found %d training images for %s", image_count, subject_slug)

    # 2. Auto-caption
    captioned = auto_caption_images(training_dir, trigger_word)
    result["images_captioned"] = captioned

    # 3. Generate config
    lora_dir.mkdir(parents=True, exist_ok=True)
    config = generate_training_config(
        subject_slug=subject_slug,
        training_dir=training_dir,
        output_dir=lora_dir,
        trigger_word=trigger_word,
        config_overrides={
            "network_dim": rank,
            "network_alpha": rank // 2,
            "max_train_steps": steps,
            "learning_rate": learning_rate,
            "unet_lr": learning_rate,
        },
    )

    config_path = training_dir / "config.toml"
    write_toml_config(config, config_path)
    result["config_path"] = str(config_path)

    # 4. Execute training
    train_result = run_training(config_path, gpu_id=gpu_id, dry_run=dry_run)
    result.update(train_result)

    # 5. Save metadata
    if result.get("status") == "success":
        metadata = {
            "subject": subject_slug,
            "trigger_word": trigger_word,
            "rank": rank,
            "steps": steps,
            "learning_rate": learning_rate,
            "training_images": image_count,
            "duration_seconds": result.get("duration_seconds"),
            "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "lora_file": f"{subject_slug}_v1.safetensors",
        }
        meta_path = lora_dir / f"{subject_slug}_v1_metadata.json"
        meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        result["metadata_path"] = str(meta_path)
        logger.info("Training metadata saved to %s", meta_path)

    return result


# ─── CLI ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Train subject LoRA for identity preservation")
    parser.add_argument("--subject", type=str, required=True,
                        help="Subject slug (e.g., 'peta-jensen')")
    parser.add_argument("--gpu", type=int, default=4,
                        help="GPU device ID (default: 4 = FOUNDRY spare)")
    parser.add_argument("--rank", type=int, default=64,
                        help="LoRA network rank/dim (default: 64)")
    parser.add_argument("--steps", type=int, default=2000,
                        help="Training steps (default: 2000)")
    parser.add_argument("--lr", type=float, default=0.0008,
                        help="Learning rate (default: 0.0008)")
    parser.add_argument("--trigger-word", type=str, default=None,
                        help="Trigger word (default: sks_{slug})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't actually train, just generate config")
    args = parser.parse_args()

    print(f"LoRA Training Pipeline for: {args.subject}")
    print(f"  GPU: {args.gpu}")
    print(f"  Rank: {args.rank}")
    print(f"  Steps: {args.steps}")
    print(f"  LR: {args.lr}")
    print(f"  Subjects dir: {SUBJECTS_DIR}")
    print(f"{'=' * 60}")

    result = train_subject_lora(
        subject_slug=args.subject,
        gpu_id=args.gpu,
        rank=args.rank,
        steps=args.steps,
        learning_rate=args.lr,
        trigger_word=args.trigger_word,
        dry_run=args.dry_run,
    )

    print(f"\n{'=' * 60}")
    print(f"RESULT: {result['status']}")
    for k, v in result.items():
        if k != "status":
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
