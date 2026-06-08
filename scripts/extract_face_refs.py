#!/usr/bin/env python3
"""Extract face reference images from VAULT stash video library.

Extracts high-quality face frames from performer videos for use as
PuLID/InfiniteYou face-ID references and optionally LoRA training data.

Two extraction modes:
  Mode 1 (--mode refs):   5-10 best face images for face-ID inference
  Mode 2 (--mode train):  30-50 diverse frames for LoRA training

Source: /mnt/vault/data/vault/stash/{PerformerName}/
Output: /mnt/vault/data/gen-subjects/{slug}/
        /mnt/vault/data/gen-subjects/{slug}/training/50_sks_{slug}/

Requirements:
    pip install opencv-python numpy insightface onnxruntime-gpu
    ffmpeg must be on PATH

Designed to run on FOUNDRY GPU 4 (spare RTX 5070 Ti) for fast processing.

Usage:
    python scripts/extract_face_refs.py --performers "Peta Jensen,Madison Ivy"
    python scripts/extract_face_refs.py --performers "Peta Jensen" --mode train --max-refs 50
    python scripts/extract_face_refs.py --all-s-tier
    python scripts/extract_face_refs.py --all-tiered --min-tier B
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

try:
    import cv2
except ImportError:
    print("ERROR: opencv-python required. Install: pip install opencv-python")
    sys.exit(1)

try:
    from insightface.app import FaceAnalysis
except ImportError:
    FaceAnalysis = None
    print("WARNING: insightface not available — using OpenCV Haar cascade fallback")


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("extract_refs")


# ─── Config ──────────────────────────────────────────────────────────────

STASH_DIR = Path(os.environ.get("STASH_DIR", "/mnt/vault/data/vault/stash"))
SUBJECTS_DIR = Path(os.environ.get("GEN_SUBJECTS_DIR", "/mnt/vault/data/gen-subjects"))
PERFORMERS_JSON = Path(os.environ.get("PERFORMERS_JSON", "/mnt/vault/data/performers.json"))

# Quality thresholds
MIN_FACE_SIZE = 200       # pixels — minimum face detection box size
MIN_BLUR_SCORE = 80       # Laplacian variance — reject blurry frames
MIN_BRIGHTNESS = 40       # mean pixel value — reject too dark
MAX_BRIGHTNESS = 240      # reject overexposed
DETECTION_CONFIDENCE = 0.5  # face detection confidence threshold

# Frame extraction settings
FRAME_INTERVAL_SECS = 10  # extract every N seconds (for initial pass)
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".wmv", ".mov", ".flv", ".webm"}


# ─── Helpers ─────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def find_stash_dir(performer_name: str) -> Path | None:
    """Find a performer's directory in the stash library."""
    if not STASH_DIR.exists():
        return None

    # Try exact match first
    for d in STASH_DIR.iterdir():
        if d.is_dir() and d.name.lower().replace(" ", "") == performer_name.lower().replace(" ", ""):
            return d

    # Try fuzzy match
    slug = slugify(performer_name)
    for d in STASH_DIR.iterdir():
        if d.is_dir() and slugify(d.name) == slug:
            return d

    return None


def get_video_files(stash_path: Path, max_videos: int = 5) -> list[Path]:
    """Get the best video files (largest/highest res) from a stash directory."""
    videos = [
        f for f in stash_path.rglob("*")
        if f.suffix.lower() in VIDEO_EXTENSIONS and f.stat().st_size > 10_000_000
    ]
    # Sort by size (largest = likely highest quality)
    videos.sort(key=lambda f: f.stat().st_size, reverse=True)
    return videos[:max_videos]


def extract_frames_ffmpeg(video_path: Path, output_dir: Path,
                          interval_secs: int = 10, max_frames: int = 200) -> list[Path]:
    """Extract frames from video using ffmpeg at uniform intervals."""
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = output_dir / f"frame_%04d.jpg"

    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", f"fps=1/{interval_secs}",
        "-frames:v", str(max_frames),
        "-q:v", "2",  # high quality JPEG
        str(pattern),
        "-y", "-loglevel", "warning",
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    except FileNotFoundError:
        logger.error("ffmpeg not found on PATH")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg timed out for %s", video_path.name)
    except subprocess.CalledProcessError as e:
        logger.warning("ffmpeg error for %s: %s", video_path.name, e.stderr[:200] if e.stderr else "")

    frames = sorted(output_dir.glob("frame_*.jpg"))
    return frames


def compute_blur_score(image: np.ndarray) -> float:
    """Laplacian variance — higher = sharper."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    return cv2.Laplacian(gray, cv2.CV_64F).var()


def compute_brightness(image: np.ndarray) -> float:
    """Mean pixel brightness."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    return float(gray.mean())


# ─── Face Detection ──────────────────────────────────────────────────────

class FaceDetector:
    """Face detection using InsightFace (preferred) or OpenCV Haar cascade."""

    def __init__(self, use_gpu: bool = True):
        self._insight = None
        self._cascade = None

        if FaceAnalysis is not None:
            try:
                providers = ["CUDAExecutionProvider"] if use_gpu else ["CPUExecutionProvider"]
                self._insight = FaceAnalysis(
                    name="buffalo_l",
                    providers=providers,
                )
                self._insight.prepare(ctx_id=0 if use_gpu else -1, det_size=(640, 640))
                logger.info("Using InsightFace (buffalo_l) for face detection")
                return
            except Exception as e:
                logger.warning("InsightFace init failed: %s — falling back to Haar", e)

        # Fallback: OpenCV Haar cascade
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self._cascade = cv2.CascadeClassifier(cascade_path)
        logger.info("Using OpenCV Haar cascade for face detection")

    def detect(self, image: np.ndarray) -> list[dict]:
        """Detect faces and return list of {bbox, score, size}."""
        if self._insight:
            return self._detect_insight(image)
        return self._detect_haar(image)

    def _detect_insight(self, image: np.ndarray) -> list[dict]:
        faces = self._insight.get(image)
        results = []
        for face in faces:
            bbox = face.bbox.astype(int)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            results.append({
                "bbox": (int(bbox[0]), int(bbox[1]), int(w), int(h)),
                "score": float(face.det_score),
                "size": max(w, h),
                "embedding": face.embedding if hasattr(face, "embedding") else None,
            })
        return results

    def _detect_haar(self, image: np.ndarray) -> list[dict]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        faces = self._cascade.detectMultiScale(gray, 1.1, 5, minSize=(100, 100))
        results = []
        for (x, y, w, h) in faces:
            results.append({
                "bbox": (x, y, w, h),
                "score": 0.8,  # Haar doesn't provide confidence
                "size": max(w, h),
                "embedding": None,
            })
        return results


# ─── Frame Quality Filter ────────────────────────────────────────────────

def filter_quality_frames(
    frame_paths: list[Path],
    detector: FaceDetector,
    min_face_size: int = MIN_FACE_SIZE,
    min_blur: float = MIN_BLUR_SCORE,
) -> list[dict]:
    """Filter frames for quality and face presence.

    Returns list of {path, face_bbox, face_size, blur_score, brightness, score}.
    """
    candidates = []

    for fp in frame_paths:
        img = cv2.imread(str(fp))
        if img is None:
            continue

        # Quality checks
        blur = compute_blur_score(img)
        if blur < min_blur:
            continue

        brightness = compute_brightness(img)
        if brightness < MIN_BRIGHTNESS or brightness > MAX_BRIGHTNESS:
            continue

        # Face detection
        faces = detector.detect(img)
        if not faces:
            continue

        # Filter: exactly 1 face, adequate size
        # For now, take the largest face if multiple detected
        best_face = max(faces, key=lambda f: f["size"])
        if best_face["size"] < min_face_size:
            continue
        if best_face["score"] < DETECTION_CONFIDENCE:
            continue

        # Composite quality score
        score = (
            best_face["score"] * 30 +          # Detection confidence
            min(blur / 500, 1.0) * 30 +         # Sharpness
            best_face["size"] / 500 * 20 +       # Face size
            (1 - abs(brightness - 128) / 128) * 20  # Brightness balance
        )

        candidates.append({
            "path": fp,
            "face_bbox": best_face["bbox"],
            "face_size": best_face["size"],
            "blur_score": blur,
            "brightness": brightness,
            "detection_score": best_face["score"],
            "score": score,
        })

    return candidates


def select_diverse_frames(candidates: list[dict], max_refs: int = 10) -> list[dict]:
    """Select diverse frames — avoid picking too-similar images."""
    if len(candidates) <= max_refs:
        return candidates

    # Sort by quality score
    candidates.sort(key=lambda x: x["score"], reverse=True)

    selected = [candidates[0]]
    for c in candidates[1:]:
        if len(selected) >= max_refs:
            break

        # Simple diversity: ensure frames aren't too close together
        # (frame index distance as proxy for temporal diversity)
        too_similar = False
        c_idx = int(re.search(r"(\d+)", c["path"].stem).group(1)) if re.search(r"(\d+)", c["path"].stem) else 0
        for s in selected:
            s_idx = int(re.search(r"(\d+)", s["path"].stem).group(1)) if re.search(r"(\d+)", s["path"].stem) else 0
            if abs(c_idx - s_idx) < 3:  # Too close temporally
                too_similar = True
                break

        if not too_similar:
            selected.append(c)

    return selected


# ─── Main Pipeline ───────────────────────────────────────────────────────

def extract_refs_for_performer(
    performer_name: str,
    mode: str = "refs",
    max_refs: int = 10,
    max_videos: int = 3,
    detector: FaceDetector | None = None,
    force: bool = False,
) -> dict:
    """Extract face references for a single performer.

    Args:
        performer_name: Display name (e.g. "Peta Jensen")
        mode: "refs" (5-10 images for face-ID) or "train" (30-50 for LoRA)
        max_refs: Maximum images to extract
        max_videos: Maximum source videos to process
        detector: Shared FaceDetector instance
        force: Overwrite existing refs

    Returns:
        Dict with extraction results.
    """
    slug = slugify(performer_name)
    result = {
        "performer": performer_name,
        "slug": slug,
        "status": "pending",
        "refs_extracted": 0,
        "output_dir": "",
    }

    # Check stash directory
    stash_dir = find_stash_dir(performer_name)
    if not stash_dir:
        result["status"] = "no_stash_dir"
        logger.warning("No stash directory found for %s", performer_name)
        return result

    # Check output directory
    if mode == "train":
        output_dir = SUBJECTS_DIR / slug / "training" / f"50_sks_{slug}"
    else:
        output_dir = SUBJECTS_DIR / slug

    result["output_dir"] = str(output_dir)

    # Check if already has refs
    if not force and output_dir.exists():
        existing = [
            f for f in output_dir.iterdir()
            if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        ]
        if existing and len(existing) >= max_refs // 2:
            result["status"] = "already_exists"
            result["refs_extracted"] = len(existing)
            logger.info("%s: already has %d refs, skipping (use --force to overwrite)",
                        performer_name, len(existing))
            return result

    # Get video files
    videos = get_video_files(stash_dir, max_videos)
    if not videos:
        result["status"] = "no_videos"
        logger.warning("No video files found for %s in %s", performer_name, stash_dir)
        return result

    logger.info("Processing %s: %d videos found in %s", performer_name, len(videos), stash_dir)

    if detector is None:
        detector = FaceDetector()

    # Extract and filter frames from all videos
    all_candidates = []
    with tempfile.TemporaryDirectory(prefix=f"refs_{slug}_") as tmp:
        tmp_path = Path(tmp)

        for i, video in enumerate(videos):
            logger.info("  Video %d/%d: %s (%.1f GB)",
                        i + 1, len(videos), video.name, video.stat().st_size / 1e9)

            # Extract frames
            video_tmp = tmp_path / f"video_{i}"
            frames = extract_frames_ffmpeg(
                video, video_tmp,
                interval_secs=FRAME_INTERVAL_SECS,
                max_frames=200 if mode == "train" else 100,
            )
            logger.info("    Extracted %d frames", len(frames))

            if not frames:
                continue

            # Filter for quality + face
            candidates = filter_quality_frames(frames, detector)
            logger.info("    %d quality candidates with faces", len(candidates))

            all_candidates.extend(candidates)

        # ── Still inside temp dir context ── selection + copy must happen here
        # because frame["path"] points to files inside the temp directory
        if not all_candidates:
            result["status"] = "no_faces_found"
            logger.warning("No quality face frames found for %s", performer_name)
            return result

        # Select diverse subset
        selected = select_diverse_frames(all_candidates, max_refs)
        logger.info("Selected %d diverse frames for %s", len(selected), performer_name)

        # Copy selected frames to output
        output_dir.mkdir(parents=True, exist_ok=True)

        saved_count = 0
        for i, frame in enumerate(selected):
            src = frame["path"]
            ext = src.suffix
            if mode == "train":
                dst = output_dir / f"img_{i + 1:03d}{ext}"
            else:
                dst = output_dir / f"ref_{i + 1:02d}{ext}"

            # Read, optionally crop to face region with padding, and save
            img = cv2.imread(str(src))
            if img is not None:
                cv2.imwrite(str(dst), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
                saved_count += 1
            else:
                logger.warning("Failed to read frame: %s", src)

        result["status"] = "success"
        result["refs_extracted"] = saved_count
        logger.info("✓ %s: %d refs saved to %s", performer_name, saved_count, output_dir)

    return result


# ─── CLI ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Extract face references from VAULT stash videos")
    parser.add_argument("--performers", type=str, default="",
                        help="Comma-separated performer names")
    parser.add_argument("--all-s-tier", action="store_true",
                        help="Process all S-tier performers from performers.json")
    parser.add_argument("--all-tiered", action="store_true",
                        help="Process all tiered (S/A/B) performers")
    parser.add_argument("--min-tier", type=str, default="S",
                        choices=["S", "A", "B"],
                        help="Minimum tier to process (with --all-tiered)")
    parser.add_argument("--mode", type=str, default="refs",
                        choices=["refs", "train"],
                        help="refs=5-10 face-ID images, train=30-50 LoRA training images")
    parser.add_argument("--max-refs", type=int, default=10,
                        help="Maximum reference images to extract per performer")
    parser.add_argument("--max-videos", type=int, default=3,
                        help="Maximum source videos to process per performer")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing refs")
    parser.add_argument("--no-gpu", action="store_true",
                        help="Use CPU for face detection")
    args = parser.parse_args()

    # Build performer list
    performer_names = []

    if args.performers:
        performer_names = [n.strip() for n in args.performers.split(",") if n.strip()]

    if args.all_s_tier or args.all_tiered:
        if PERFORMERS_JSON.exists():
            data = json.loads(PERFORMERS_JSON.read_text())
            performers = data if isinstance(data, list) else data.get("performers", [])

            tier_order = {"S": 0, "A": 1, "B": 2}
            min_tier_idx = tier_order.get(args.min_tier, 0)

            for p in performers:
                tier = p.get("tier", "")
                if not tier:
                    continue
                if args.all_s_tier and tier != "S":
                    continue
                if args.all_tiered and tier_order.get(tier, 99) > min_tier_idx:
                    continue
                performer_names.append(p["name"])
        else:
            logger.error("performers.json not found at %s", PERFORMERS_JSON)
            sys.exit(1)

    if not performer_names:
        parser.print_help()
        print("\nNo performers specified. Use --performers or --all-s-tier")
        sys.exit(1)

    # Adjust max_refs based on mode
    if args.mode == "train" and args.max_refs == 10:
        args.max_refs = 50  # Default for training mode

    print(f"Extracting {args.mode} for {len(performer_names)} performers")
    print(f"  Stash dir: {STASH_DIR}")
    print(f"  Output dir: {SUBJECTS_DIR}")
    print(f"  Max refs: {args.max_refs}")
    print(f"  Mode: {args.mode}")
    print(f"{'=' * 60}")

    # Initialize detector once (shared across all performers)
    detector = FaceDetector(use_gpu=not args.no_gpu)

    results = []
    for name in performer_names:
        result = extract_refs_for_performer(
            performer_name=name,
            mode=args.mode,
            max_refs=args.max_refs,
            max_videos=args.max_videos,
            detector=detector,
            force=args.force,
        )
        results.append(result)

    # Summary
    print(f"\n{'=' * 60}")
    print("EXTRACTION SUMMARY")
    success = sum(1 for r in results if r["status"] == "success")
    existing = sum(1 for r in results if r["status"] == "already_exists")
    failed = sum(1 for r in results if r["status"] not in ("success", "already_exists"))
    total_refs = sum(r["refs_extracted"] for r in results)

    print(f"  Success: {success}")
    print(f"  Already existed: {existing}")
    print(f"  Failed: {failed}")
    print(f"  Total refs extracted: {total_refs}")

    for r in results:
        icon = "✓" if r["status"] == "success" else "=" if r["status"] == "already_exists" else "✗"
        print(f"  {icon} {r['performer']}: {r['status']} ({r['refs_extracted']} refs)")


if __name__ == "__main__":
    main()
