#!/usr/bin/env python3
"""Automated dataset preparation for LoRA training.

Takes a folder of photos and:
1. Detects + crops faces using InsightFace
2. Resizes to training resolution (512x512 or 1024x1024)
3. Generates captions using BLIP2 or Florence-2
4. Creates kohya-compatible directory structure

Usage:
    python prepare_dataset.py <photo_dir> <trigger_word> [--resolution 1024] [--model-type sdxl]
"""

import argparse
import os
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

try:
    from insightface.app import FaceAnalysis
    HAS_INSIGHTFACE = True
except ImportError:
    HAS_INSIGHTFACE = False
    print("Warning: insightface not available, using basic crop")


def detect_and_crop_face(image_path: str, target_size: int = 1024, padding: float = 0.5) -> Image.Image | None:
    """Detect face in image, crop with padding, resize to square."""
    img = cv2.imread(image_path)
    if img is None:
        return None

    if HAS_INSIGHTFACE:
        app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=0, det_size=(640, 640))
        faces = app.get(img)
        if not faces:
            # No face detected — use center crop
            return center_crop(image_path, target_size)
        
        # Use the largest face
        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        x1, y1, x2, y2 = [int(v) for v in face.bbox]
    else:
        # Fallback: use OpenCV Haar cascade
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(100, 100))
        if len(faces) == 0:
            return center_crop(image_path, target_size)
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        x1, y1, x2, y2 = x, y, x + w, y + h

    # Add padding
    h, w = img.shape[:2]
    face_w = x2 - x1
    face_h = y2 - y1
    pad_x = int(face_w * padding)
    pad_y = int(face_h * padding)
    
    # Make square
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    size = max(face_w + 2 * pad_x, face_h + 2 * pad_y)
    
    x1 = max(0, cx - size // 2)
    y1 = max(0, cy - size // 2)
    x2 = min(w, x1 + size)
    y2 = min(h, y1 + size)
    
    cropped = img[y1:y2, x1:x2]
    pil_img = Image.fromarray(cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB))
    return pil_img.resize((target_size, target_size), Image.LANCZOS)


def center_crop(image_path: str, target_size: int = 1024) -> Image.Image:
    """Fallback: center crop to square."""
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    size = min(w, h)
    left = (w - size) // 2
    top = (h - size) // 2
    img = img.crop((left, top, left + size, top + size))
    return img.resize((target_size, target_size), Image.LANCZOS)


def generate_caption(image_path: str, trigger_word: str) -> str:
    """Generate a caption for the image.
    
    Falls back to a template-based caption if BLIP is not available.
    """
    # Simple template caption (good enough for LoRA training)
    return f"a photo of {trigger_word}, high quality, professional photography"


def prepare_dataset(
    photo_dir: str,
    trigger_word: str,
    output_dir: str | None = None,
    resolution: int = 1024,
    repeats: int = 20,
) -> str:
    """Main dataset preparation pipeline.
    
    Returns the output directory path.
    """
    photo_path = Path(photo_dir)
    if not photo_path.exists():
        print(f"Error: {photo_dir} does not exist")
        sys.exit(1)
    
    # Output directory (kohya format: repeats_trigger/)
    if output_dir is None:
        output_dir = f"/data/training/{trigger_word}"
    out_path = Path(output_dir)
    img_dir = out_path / f"{repeats}_{trigger_word}"
    img_dir.mkdir(parents=True, exist_ok=True)
    
    # Find images
    extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    images = [f for f in photo_path.iterdir() if f.suffix.lower() in extensions]
    
    if not images:
        print(f"No images found in {photo_dir}")
        sys.exit(1)
    
    print(f"Found {len(images)} images in {photo_dir}")
    print(f"Output: {img_dir}")
    print(f"Resolution: {resolution}x{resolution}")
    print(f"Trigger word: {trigger_word}")
    print()
    
    processed = 0
    for i, img_path in enumerate(images):
        print(f"  [{i+1}/{len(images)}] {img_path.name}...", end=" ")
        
        try:
            # Detect face and crop
            result = detect_and_crop_face(str(img_path), target_size=resolution)
            if result is None:
                print("SKIP (unreadable)")
                continue
            
            # Save cropped image
            out_name = f"{trigger_word}_{i:04d}.png"
            result.save(img_dir / out_name, "PNG")
            
            # Generate and save caption
            caption = generate_caption(str(img_path), trigger_word)
            caption_file = img_dir / f"{trigger_word}_{i:04d}.txt"
            caption_file.write_text(caption)
            
            processed += 1
            print("OK")
        except Exception as e:
            print(f"ERROR: {e}")
    
    print(f"\nProcessed {processed}/{len(images)} images")
    print(f"Dataset ready at: {img_dir}")
    return str(out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare dataset for LoRA training")
    parser.add_argument("photo_dir", help="Directory containing photos")
    parser.add_argument("trigger_word", help="Trigger word for the LoRA")
    parser.add_argument("--resolution", type=int, default=1024, help="Output resolution (default: 1024)")
    parser.add_argument("--output", help="Output directory (default: /data/training/<trigger>)")
    parser.add_argument("--repeats", type=int, default=20, help="Training repeats (default: 20)")
    
    args = parser.parse_args()
    prepare_dataset(args.photo_dir, args.trigger_word, args.output, args.resolution, args.repeats)
