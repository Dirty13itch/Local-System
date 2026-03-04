"""Queen Profile Loader — parses EoBQ Master Document for queen data.

Extracts structured queen profiles from the 81.3KB Master Document markdown,
including physical blueprints, DNA traits, Flux prompts, and scene definitions.

Loads once at startup, cached in memory, served via REST.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from local_system.models import QueenDNA, QueenProfile, QueenScene

logger = logging.getLogger("gateway.queens")

# Path to Master Document on DEV
MASTER_DOC_PATH = os.environ.get(
    "EOQB_MASTER_DOC",
    os.path.expanduser("~/dev/docs"),
)

# Path to performer reference images
PERFORMER_REFS_PATH = os.environ.get(
    "PERFORMER_REFS_PATH",
    "/mnt/vault/data/performer-refs",
)

# Cached queen profiles (loaded once)
_queen_cache: list[QueenProfile] = []
_queen_map: dict[str, QueenProfile] = {}


def _slugify(name: str) -> str:
    """Convert a queen name to a URL-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _find_master_doc() -> Path | None:
    """Locate the Master Document file."""
    doc_dir = Path(MASTER_DOC_PATH)
    if not doc_dir.exists():
        return None
    for f in doc_dir.iterdir():
        if "broken queens" in f.name.lower() and f.suffix == ".md":
            return f
    # Also check for any .md file with "master document" in the name
    for f in doc_dir.iterdir():
        if "master document" in f.name.lower() and f.suffix == ".md":
            return f
    return None


def _parse_dna_traits(section: str) -> dict[str, int]:
    """Extract DNA trait scores from a section of text."""
    traits = {}
    trait_names = [
        "dominance", "submission", "exhibitionism", "voyeurism", "nurturing",
        "corruption", "possessiveness", "devotion", "playfulness", "intensity",
        "ritualism", "spontaneity", "emotional_openness", "guardedness",
        "sensory_focus", "intellectual_arousal", "power_exchange",
        "intimacy_threshold", "taboo_comfort",
    ]
    for trait in trait_names:
        # Match patterns like "Dominance: 8" or "dominance = 8" or "Dominance - 8/10"
        display_name = trait.replace("_", " ").title()
        patterns = [
            rf"{display_name}\s*[:=\-–]\s*(\d+)",
            rf"{trait}\s*[:=\-–]\s*(\d+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, section, re.IGNORECASE)
            if m:
                traits[trait] = min(10, max(1, int(m.group(1))))
                break
    return traits


def _parse_physical_blueprint(section: str) -> dict[str, Any]:
    """Extract physical attributes from a section."""
    blueprint: dict[str, Any] = {}

    patterns = {
        "height": r"height\s*[:=]\s*([^\n,]+)",
        "bust": r"bust\s*[:=]\s*([^\n,]+)",
        "waist": r"waist\s*[:=]\s*([^\n,]+)",
        "hips": r"hips?\s*[:=]\s*([^\n,]+)",
        "hair": r"hair\s*[:=]\s*([^\n,]+)",
        "eyes": r"eyes?\s*[:=]\s*([^\n,]+)",
        "build": r"build\s*[:=]\s*([^\n,]+)",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, section, re.IGNORECASE)
        if m:
            blueprint[key] = m.group(1).strip()

    return blueprint


def _extract_flux_prompt(section: str) -> str:
    """Extract Flux generation prompt from a section."""
    # Look for code blocks containing prompts
    m = re.search(r"```(?:flux|prompt)?\s*\n(.*?)```", section, re.DOTALL)
    if m:
        return m.group(1).strip()

    # Look for lines starting with "Prompt:" or "Flux Prompt:"
    m = re.search(r"(?:flux\s+)?prompt\s*:\s*(.+?)(?:\n\n|\n#)", section, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()

    return ""


def load_queens() -> list[QueenProfile]:
    """Parse the Master Document and return all queen profiles.

    Returns cached profiles on subsequent calls.
    """
    global _queen_cache, _queen_map

    if _queen_cache:
        return _queen_cache

    doc_path = _find_master_doc()
    if not doc_path:
        logger.warning("Master Document not found at %s", MASTER_DOC_PATH)
        return []

    logger.info("Loading queens from %s", doc_path)

    try:
        content = doc_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error("Failed to read Master Document: %s", e)
        return []

    # Split by queen sections — look for ## Queen patterns or numbered sections
    # The document uses headers like "## Queen 1: Name" or "## 1. Queen Name"
    queen_sections = re.split(r"(?=^##\s+(?:Queen\s+\d+|[\d]+\.)\s*)", content, flags=re.MULTILINE)

    queens: list[QueenProfile] = []

    for section in queen_sections:
        if not section.strip():
            continue

        # Extract queen name from header
        header_match = re.match(
            r"##\s+(?:Queen\s+\d+[:\s]+|[\d]+\.\s+)(.+?)(?:\n|$)", section
        )
        if not header_match:
            continue

        name = header_match.group(1).strip().rstrip("#").strip()
        if not name:
            continue

        queen_id = _slugify(name)

        # Extract performer reference
        performer_match = re.search(
            r"(?:performer|inspiration|based on|reference)\s*[:=]\s*(.+?)(?:\n|$)",
            section, re.IGNORECASE,
        )
        performer_ref = performer_match.group(1).strip() if performer_match else ""

        # Extract physical blueprint
        blueprint = _parse_physical_blueprint(section)

        # Extract DNA traits
        dna_traits = _parse_dna_traits(section)
        dna = QueenDNA(**dna_traits) if dna_traits else QueenDNA()

        # Extract portrait prompt
        portrait_prompt = _extract_flux_prompt(section)

        # Extract scenes
        scenes: list[QueenScene] = []
        scene_matches = re.finditer(
            r"###\s+Scene\s+\d+[:\s]+(.+?)(?:\n)(.*?)(?=###|\Z)",
            section, re.DOTALL,
        )
        for sm in scene_matches:
            scene_title = sm.group(1).strip()
            scene_body = sm.group(2).strip()
            scene_prompt = _extract_flux_prompt(scene_body)
            scenes.append(QueenScene(
                title=scene_title,
                description=scene_body[:200] if scene_body else "",
                flux_prompt=scene_prompt,
            ))

        # Check for trained LoRA
        lora_match = re.search(r"lora\s*[:=]\s*(.+\.safetensors)", section, re.IGNORECASE)
        lora_name = lora_match.group(1).strip() if lora_match else None

        # Check for reference images
        ref_dir = Path(PERFORMER_REFS_PATH) / _slugify(performer_ref or name)
        ref_images = []
        if ref_dir.exists():
            ref_images = [f.name for f in ref_dir.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]

        queen = QueenProfile(
            id=queen_id,
            name=name,
            performer_ref=performer_ref,
            physical_blueprint=blueprint,
            dna=dna,
            flux_portrait_prompt=portrait_prompt,
            scenes=scenes,
            lora_name=lora_name,
            reference_images=ref_images,
        )
        queens.append(queen)
        _queen_map[queen_id] = queen

    _queen_cache = queens
    logger.info("Loaded %d queen profiles", len(queens))
    return queens


def get_queen(queen_id: str) -> QueenProfile | None:
    """Get a specific queen by ID."""
    if not _queen_cache:
        load_queens()
    return _queen_map.get(queen_id)


def reload_queens() -> list[QueenProfile]:
    """Force reload from disk."""
    global _queen_cache, _queen_map
    _queen_cache = []
    _queen_map = {}
    return load_queens()
