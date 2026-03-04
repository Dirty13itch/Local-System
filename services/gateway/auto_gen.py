"""Autonomous generation engine — watches drop folder, processes new entries.

Flow:
  1. User drops photos into  \\\\VAULT\\data\\gen-drops\\<person-name>\\
  2. Scanner detects new folder (no .done marker)
  3. Engine selects best reference faces, uploads to ComfyUI
  4. Generates portrait + 2 variations automatically
  5. Saves results + metadata to gen-refs/ and gen-output/
  6. Marks folder as .done

Folder layout on VAULT (NFS-mounted at /mnt/vault/data/):
  gen-drops/<name>/          ← user drops raw photos here
  gen-refs/<name>/           ← cropped refs + manifest.json
  gen-output/<name>/         ← generated images
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("auto_gen")

# ─── Configuration ────────────────────────────────────────────────────────────

# Base paths — VAULT via NFS on DEV
DROPS_DIR = Path(os.environ.get("GEN_DROPS_DIR", "/mnt/vault/data/gen-drops"))
REFS_DIR = Path(os.environ.get("GEN_REFS_DIR", "/mnt/vault/data/gen-refs"))
OUTPUT_DIR = Path(os.environ.get("GEN_OUTPUT_DIR", "/mnt/vault/data/gen-output"))

# ComfyUI
COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://localhost:8188")

# Supported image extensions
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}

# How many reference images to keep
MAX_REFS = 5

# How many auto-portraits to generate
AUTO_PORTRAITS = 3

# Scan interval in seconds
SCAN_INTERVAL = 30


# ─── Data structures ─────────────────────────────────────────────────────────


@dataclass
class DropEntry:
    """A detected drop folder with status."""
    name: str
    path: Path
    image_count: int = 0
    status: str = "pending"  # pending | processing | done | error
    error: str | None = None
    created_at: float = 0.0
    processed_at: float | None = None
    refs_created: int = 0
    images_generated: int = 0
    prompt_ids: list[str] = field(default_factory=list)


@dataclass
class DropManifest:
    """Manifest for a processed drop — saved as manifest.json in gen-refs/<name>/."""
    name: str
    source_count: int
    ref_images: list[str]
    generated_images: list[str]
    prompt_used: str
    pipeline: str
    processed_at: str
    identity_method: str  # "pulid" | "ipadapter" | "prompt_only"


# ─── Scanner ──────────────────────────────────────────────────────────────────


class AutoGenerator:
    """Watches gen-drops for new entries and processes them autonomously."""

    def __init__(self, comfyui_url: str = COMFYUI_URL):
        self.comfyui_url = comfyui_url
        self._processing: dict[str, DropEntry] = {}
        self._history: list[DropEntry] = []
        self._running = False
        self._task: asyncio.Task | None = None

    def scan_drops(self) -> list[DropEntry]:
        """Scan the drop folder for new entries."""
        entries = []

        if not DROPS_DIR.exists():
            logger.warning("Drop folder does not exist: %s", DROPS_DIR)
            return entries

        for item in sorted(DROPS_DIR.iterdir()):
            if not item.is_dir():
                continue
            if item.name.startswith("."):
                continue

            # Check if already done
            done_marker = item / ".done"
            error_marker = item / ".error"

            # Count images
            images = [f for f in item.iterdir() if f.suffix.lower() in IMAGE_EXTS]

            entry = DropEntry(
                name=item.name,
                path=item,
                image_count=len(images),
                created_at=item.stat().st_ctime,
            )

            if done_marker.exists():
                entry.status = "done"
                try:
                    entry.processed_at = done_marker.stat().st_mtime
                except OSError:
                    pass
            elif error_marker.exists():
                entry.status = "error"
                try:
                    entry.error = error_marker.read_text().strip()
                except OSError:
                    entry.error = "Unknown error"
            elif item.name in self._processing:
                entry.status = "processing"
            else:
                entry.status = "pending"

            entries.append(entry)

        return entries

    def get_pending(self) -> list[DropEntry]:
        """Get entries that need processing."""
        return [e for e in self.scan_drops() if e.status == "pending" and e.image_count > 0]

    def get_status(self) -> dict[str, Any]:
        """Get current auto-gen status."""
        entries = self.scan_drops()
        return {
            "scanner_running": self._running,
            "scan_interval": SCAN_INTERVAL,
            "drops_dir": str(DROPS_DIR),
            "total_drops": len(entries),
            "pending": len([e for e in entries if e.status == "pending"]),
            "processing": len([e for e in entries if e.status == "processing"]),
            "done": len([e for e in entries if e.status == "done"]),
            "errors": len([e for e in entries if e.status == "error"]),
            "entries": [asdict(e) for e in entries],
            "history": [asdict(e) for e in self._history[-20:]],
        }

    # ─── Processing pipeline ──────────────────────────────────────────────

    async def process_drop(self, name: str) -> DropEntry:
        """Process a single drop folder end-to-end."""
        drop_path = DROPS_DIR / name
        if not drop_path.exists():
            raise FileNotFoundError(f"Drop folder not found: {name}")

        entry = DropEntry(
            name=name,
            path=drop_path,
            status="processing",
            created_at=drop_path.stat().st_ctime,
        )
        self._processing[name] = entry

        try:
            # 1. Find all images
            images = sorted(
                [f for f in drop_path.iterdir() if f.suffix.lower() in IMAGE_EXTS],
                key=lambda f: f.stat().st_size,
                reverse=True,  # Largest (highest res) first
            )
            entry.image_count = len(images)

            if not images:
                raise ValueError(f"No images found in {name}")

            logger.info("Processing drop '%s': %d images found", name, len(images))

            # 2. Create refs directory
            refs_path = REFS_DIR / name
            refs_path.mkdir(parents=True, exist_ok=True)

            # 3. Copy best refs (up to MAX_REFS, sorted by size/quality)
            ref_files = []
            for i, img in enumerate(images[:MAX_REFS]):
                dest = refs_path / f"ref_{i:02d}{img.suffix.lower()}"
                shutil.copy2(img, dest)
                ref_files.append(dest.name)
                logger.info("  ref %d: %s (%s bytes)", i, img.name, img.stat().st_size)

            entry.refs_created = len(ref_files)

            # 4. Upload primary ref to ComfyUI
            primary_ref = refs_path / ref_files[0]
            comfy_filename = await self._upload_to_comfyui(primary_ref)

            if not comfy_filename:
                raise RuntimeError("Failed to upload reference image to ComfyUI")

            logger.info("  uploaded to ComfyUI as: %s", comfy_filename)

            # 5. Generate portraits
            output_path = OUTPUT_DIR / name
            output_path.mkdir(parents=True, exist_ok=True)

            display_name = name.replace("-", " ").replace("_", " ").title()

            prompts = [
                f"professional headshot portrait of {display_name}, studio lighting, sharp focus, "
                f"8k uhd, photorealistic, clean background, looking at camera",

                f"cinematic portrait of {display_name}, natural lighting, shallow depth of field, "
                f"warm tones, beautiful, photorealistic, 8k quality",

                f"full body portrait of {display_name}, elegant outfit, studio setting, "
                f"professional photography, soft lighting, photorealistic, 8k quality",
            ]

            generated = []
            for i, prompt in enumerate(prompts[:AUTO_PORTRAITS]):
                prompt_id = await self._submit_generation(
                    prompt=prompt,
                    ref_image=comfy_filename,
                    width=832 if i < 2 else 1024,
                    height=1216 if i < 2 else 1024,
                )
                if prompt_id:
                    entry.prompt_ids.append(prompt_id)
                    logger.info("  submitted gen %d: %s", i, prompt_id)

                    # Wait for completion and save
                    result = await self._wait_for_result(prompt_id, timeout=180)
                    if result:
                        for img_info in result:
                            filename = img_info.get("filename", "")
                            if filename:
                                # Download from ComfyUI and save to output
                                saved = await self._save_comfyui_image(
                                    filename,
                                    img_info.get("type", "output"),
                                    output_path / f"auto_{i:02d}_{filename}",
                                )
                                if saved:
                                    generated.append(saved)

            entry.images_generated = len(generated)

            # 6. Write manifest
            manifest = DropManifest(
                name=name,
                source_count=len(images),
                ref_images=ref_files,
                generated_images=[str(g) for g in generated],
                prompt_used=prompts[0],
                pipeline="flux-faceid",
                processed_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                identity_method="pulid" if comfy_filename else "prompt_only",
            )

            manifest_path = refs_path / "manifest.json"
            manifest_path.write_text(json.dumps(asdict(manifest), indent=2))

            # 7. Mark as done
            (drop_path / ".done").write_text(
                f"Processed {len(images)} images → {len(ref_files)} refs → {len(generated)} generated\n"
                f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            )

            entry.status = "done"
            entry.processed_at = time.time()
            logger.info("Drop '%s' complete: %d refs, %d generated", name, len(ref_files), len(generated))

        except Exception as e:
            entry.status = "error"
            entry.error = str(e)
            logger.error("Error processing drop '%s': %s", name, e)

            # Write error marker
            try:
                (drop_path / ".error").write_text(f"{e}\n{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            except OSError:
                pass

        finally:
            self._processing.pop(name, None)
            self._history.append(entry)

        return entry

    # ─── ComfyUI integration ─────────────────────────────────────────────

    async def _upload_to_comfyui(self, image_path: Path) -> str | None:
        """Upload an image to ComfyUI, return the filename."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                with open(image_path, "rb") as f:
                    files = {"image": (image_path.name, f, "image/jpeg")}
                    resp = await client.post(f"{self.comfyui_url}/upload/image", files=files)
                    resp.raise_for_status()
                    data = resp.json()
                    return data.get("name", "")
        except Exception as e:
            logger.error("Upload failed: %s", e)
            return None

    async def _submit_generation(
        self,
        prompt: str,
        ref_image: str | None = None,
        width: int = 832,
        height: int = 1216,
        seed: int = -1,
    ) -> str | None:
        """Submit a generation job to ComfyUI via the gateway pipeline."""
        from .pipelines import flux_faceid, flux_uncensored

        if seed == -1:
            seed = int.from_bytes(os.urandom(4), "big") % (2**31)

        client_id = str(uuid.uuid4())

        if ref_image:
            workflow = flux_faceid(
                prompt=prompt,
                reference_image=ref_image,
                width=width,
                height=height,
                seed=seed,
            )
        else:
            workflow = flux_uncensored(
                prompt=prompt,
                width=width,
                height=height,
                seed=seed,
            )

        workflow["client_id"] = client_id

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.comfyui_url}/prompt",
                    json=workflow,
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("prompt_id", "")
        except Exception as e:
            logger.error("Generation submit failed: %s", e)
            return None

    async def _wait_for_result(
        self,
        prompt_id: str,
        timeout: float = 180,
        poll_interval: float = 3.0,
    ) -> list[dict] | None:
        """Poll ComfyUI history until the prompt completes or timeout."""
        deadline = time.time() + timeout

        while time.time() < deadline:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(f"{self.comfyui_url}/history/{prompt_id}")
                    if resp.status_code == 200:
                        data = resp.json()
                        entry = data.get(prompt_id, {})
                        outputs = entry.get("outputs", {})
                        if outputs:
                            # Collect all output images
                            images = []
                            for node_id, node_out in outputs.items():
                                for img in node_out.get("images", []):
                                    images.append(img)
                            if images:
                                return images
            except Exception:
                pass

            await asyncio.sleep(poll_interval)

        logger.warning("Timeout waiting for prompt %s", prompt_id)
        return None

    async def _save_comfyui_image(
        self,
        filename: str,
        img_type: str,
        dest: Path,
    ) -> Path | None:
        """Download a generated image from ComfyUI and save locally."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.comfyui_url}/view",
                    params={"filename": filename, "type": img_type},
                )
                resp.raise_for_status()
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(resp.content)
                logger.info("  saved: %s (%d bytes)", dest.name, len(resp.content))
                return dest
        except Exception as e:
            logger.error("Failed to save image %s: %s", filename, e)
            return None

    # ─── Background scanner ───────────────────────────────────────────────

    async def _scan_loop(self):
        """Background loop that scans for and processes new drops."""
        logger.info("Auto-gen scanner started (interval=%ds, dir=%s)", SCAN_INTERVAL, DROPS_DIR)

        while self._running:
            try:
                pending = self.get_pending()
                for entry in pending:
                    logger.info("Auto-processing new drop: %s (%d images)", entry.name, entry.image_count)
                    await self.process_drop(entry.name)
            except Exception as e:
                logger.error("Scanner loop error: %s", e)

            await asyncio.sleep(SCAN_INTERVAL)

    def start_scanner(self):
        """Start the background scanner."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._scan_loop())
        logger.info("Auto-gen scanner started")

    def stop_scanner(self):
        """Stop the background scanner."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Auto-gen scanner stopped")


# ─── Singleton ────────────────────────────────────────────────────────────────

auto_gen = AutoGenerator()
