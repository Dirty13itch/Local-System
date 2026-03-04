"""Queen Profile Loader — parses EoBQ Master Document for queen data.

Extracts structured queen profiles from the Master Document markdown.
The document uses **Profile N** bold markers (not markdown headings) for each
queen, with subsections like **Physical Prime Blueprint**, **Flux.2 Prompt
Example**, **19-Trait Sexual DNA Table**, **Unique Scenes**, and **8 Endings**.

Loads once at startup, cached in memory, served via REST.
"""

from __future__ import annotations

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
    """Convert a name to a URL-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _find_master_doc() -> Path | None:
    """Locate the Master Document file."""
    doc_dir = Path(MASTER_DOC_PATH)
    if not doc_dir.exists():
        return None
    for f in doc_dir.iterdir():
        if "broken queens" in f.name.lower() and f.suffix == ".md":
            return f
    for f in doc_dir.iterdir():
        if "master document" in f.name.lower() and f.suffix == ".md":
            return f
    return None


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _extract_between_bold_sections(section: str, header: str) -> str:
    """Extract text between a **Header...** marker and the next **...** marker.

    The header parameter is treated as a prefix — the actual bold marker may
    contain extra text, e.g. **Unique Scenes (10+ Script-Ready)** matches
    when header="Unique Scenes".
    """
    pat = re.compile(
        rf"\*\*{re.escape(header)}[^*]*\*\*[:\s]*(.*?)(?=\*\*[A-Z]|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    m = pat.search(section)
    return m.group(1).strip() if m else ""


def _parse_physical_blueprint(section: str) -> dict[str, Any]:
    """Extract physical attributes from the Physical Prime Blueprint paragraph."""
    bp_text = _extract_between_bold_sections(section, "Physical Prime Blueprint")
    if not bp_text:
        return {}

    blueprint: dict[str, Any] = {}
    patterns = {
        "prime_year": r"Prime Year:\s*([^.]+)",
        "height": r"Height:\s*([^.]+)",
        "weight": r"Weight:\s*([^.]+)",
        "measurements": r"Measurements:\s*([^.]+)",
        "bra_cup": r"Bra/Cup:\s*([^.]+)",
        "implants": r"Implants:\s*([^.]+)",
        "hair": r"Hair:\s*([^.]+)",
        "eyes": r"Eyes:\s*([^.]+)",
        "skin": r"Skin:\s*([^.]+)",
        "tattoos_piercings": r"Tattoos/Piercings:\s*([^.]+)",
        "body_type": r"Body Type:\s*([^.]+)",
        "face_shape": r"Face Shape:\s*([^.]+)",
        "key_prime_trait": r"Key Prime Trait:\s*([^.]+)",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, bp_text, re.IGNORECASE)
        if m:
            blueprint[key] = m.group(1).strip().rstrip(".")

    return blueprint


def _extract_flux_prompt(section: str) -> str:
    """Extract Flux generation prompt from the section.

    The document format is:
      **Flux.2 Prompt Example**: "hyperreal 4K ..."
    """
    # Match the bold header followed by a quoted string.
    # Use greedy match because prompts may contain internal quotes (e.g. 5'10")
    m = re.search(
        r'\*\*Flux\.?\d?\s*Prompt\s*Example\*\*[:\s]*"(.+)"',
        section,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    # Fallback: code block
    m = re.search(r"```(?:flux|prompt)?\s*\n(.*?)```", section, re.DOTALL)
    if m:
        return m.group(1).strip()

    # Fallback: inline prompt after "Flux prompt:"
    m = re.search(r'[Ff]lux prompt:\s*"([^"]+)"', section)
    if m:
        return m.group(1).strip()

    return ""


def _parse_dna_table(section: str) -> dict[str, int]:
    """Parse the 19-Trait Sexual DNA Table from its markdown table format.

    The document uses traits like 'Pain Tolerance', 'Exhibitionism Level', etc.
    which differ from the QueenDNA model fields. This function extracts all
    numeric values and maps them to the closest QueenDNA fields.
    """
    dna_text = _extract_between_bold_sections(section, "19-Trait Sexual DNA Table")
    if not dna_text:
        return {}

    # Parse all table rows: | Trait Name | Value |
    raw: dict[str, str] = {}
    for m in re.finditer(r"\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", dna_text):
        trait_name = m.group(1).strip()
        value = m.group(2).strip()
        # Skip header and separator rows
        if trait_name.startswith("-") or trait_name.lower() == "trait":
            continue
        raw[trait_name.lower()] = value

    # Map document traits to QueenDNA model fields
    traits: dict[str, int] = {}

    # Direct numeric mappings
    _map_numeric(raw, traits, "pain tolerance", "intensity")
    _map_numeric(raw, traits, "humiliation enjoyment", "submission")
    _map_numeric(raw, traits, "exhibitionism level", "exhibitionism")
    _map_numeric(raw, traits, "switch potential", "power_exchange")
    _map_numeric(raw, traits, "betrayal threshold", "guardedness", invert=True)

    # Descriptive trait inference
    _infer_from_descriptive(raw, traits)

    return traits


def _map_numeric(
    raw: dict[str, str],
    out: dict[str, int],
    doc_key: str,
    model_key: str,
    invert: bool = False,
) -> None:
    """Map a numeric document trait to a model trait."""
    val = raw.get(doc_key, "")
    m = re.match(r"(\d+)", val)
    if m:
        score = min(10, max(1, int(m.group(1))))
        if invert:
            score = 11 - score  # 2 → 9, 8 → 3, etc.
        out[model_key] = score


def _infer_from_descriptive(raw: dict[str, str], traits: dict[str, int]) -> None:
    """Infer QueenDNA traits from descriptive (non-numeric) document values."""
    # Addiction Speed → intimacy_threshold (inverse: faster addiction = lower threshold)
    addiction = raw.get("addiction speed", "").lower()
    if "instant" in addiction:
        traits.setdefault("intimacy_threshold", 2)
    elif "fast" in addiction:
        traits.setdefault("intimacy_threshold", 3)
    elif "slow" in addiction:
        traits.setdefault("intimacy_threshold", 7)

    # Jealousy Type → possessiveness
    jealousy = raw.get("jealousy type", "").lower()
    if "possessive" in jealousy:
        traits.setdefault("possessiveness", 8)
    elif "competitive" in jealousy:
        traits.setdefault("possessiveness", 6)
    elif "none" in jealousy:
        traits.setdefault("possessiveness", 2)

    # Aftercare Need → emotional_openness
    aftercare = raw.get("aftercare need", "").lower()
    if "heavy" in aftercare:
        traits.setdefault("emotional_openness", 8)
        traits.setdefault("nurturing", 3)  # needs nurturing, not gives it
    elif "none" in aftercare:
        traits.setdefault("emotional_openness", 3)

    # Group Sex Attitude → voyeurism / exhibitionism boost
    group = raw.get("group sex attitude", "").lower()
    if "initiates" in group:
        traits.setdefault("voyeurism", 7)
        # Boost exhibitionism if not already set
        if "exhibitionism" not in traits:
            traits["exhibitionism"] = 8
    elif "curious" in group:
        traits.setdefault("voyeurism", 5)

    # Desire Type → spontaneity
    desire = raw.get("desire type", "").lower()
    if "spontaneous" in desire:
        traits.setdefault("spontaneity", 8)
    elif "responsive" in desire:
        traits.setdefault("spontaneity", 4)
    elif "hybrid" in desire:
        traits.setdefault("spontaneity", 6)

    # Roleplay Affinity → ritualism / intellectual_arousal
    roleplay = raw.get("roleplay affinity", "").lower()
    if roleplay:
        traits.setdefault("ritualism", 6)
        traits.setdefault("intellectual_arousal", 6)

    # Blackmail Need → corruption / taboo_comfort
    blackmail = raw.get("blackmail need", "").lower()
    if "begs" in blackmail:
        traits.setdefault("corruption", 9)
        traits.setdefault("taboo_comfort", 9)
    elif "heightens" in blackmail:
        traits.setdefault("corruption", 7)
        traits.setdefault("taboo_comfort", 7)
    elif "refuses" in blackmail or "no" in blackmail:
        traits.setdefault("corruption", 2)
        traits.setdefault("taboo_comfort", 3)

    # Awakening Type → devotion / playfulness
    awakening = raw.get("awakening type", "").lower()
    if "total surprise" in awakening:
        traits.setdefault("devotion", 7)
    elif "always knew" in awakening:
        traits.setdefault("devotion", 5)
        traits.setdefault("playfulness", 7)

    # Sensory focus — infer from moaning style
    moaning = raw.get("moaning style", "").lower()
    if "loud" in moaning or "animal" in moaning:
        traits.setdefault("sensory_focus", 8)
    elif "quiet" in moaning or "breathy" in moaning:
        traits.setdefault("sensory_focus", 5)


def _extract_scenes(section: str) -> list[QueenScene]:
    """Extract scenes from the numbered list after **Unique Scenes**."""
    scenes_text = _extract_between_bold_sections(section, "Unique Scenes")
    if not scenes_text:
        return []

    scenes: list[QueenScene] = []
    # Match numbered items: "1. Title: description" or "1. Title – description"
    for m in re.finditer(
        r"(\d+)\.\s+(.+?)(?:\n|$)", scenes_text
    ):
        line = m.group(2).strip()
        # Split on first colon or dash to get title vs description
        parts = re.split(r"[:\–—]\s*", line, maxsplit=1)
        title = parts[0].strip().strip('"').strip("'")
        desc = parts[1].strip() if len(parts) > 1 else ""

        # Extract Flux prompt if present
        flux_prompt = ""
        pm = re.search(r'[Ff]lux prompt:\s*"([^"]+)"', desc)
        if pm:
            flux_prompt = pm.group(1).strip()

        scenes.append(QueenScene(
            title=title,
            description=desc[:300] if desc else "",
            flux_prompt=flux_prompt,
        ))

    return scenes


def _extract_endings(section: str) -> list[str]:
    """Extract the 8 endings from **8 Endings** section."""
    endings_text = _extract_between_bold_sections(section, "8 Endings")
    if not endings_text:
        return []

    endings: list[str] = []
    for m in re.finditer(r"\d+\.\s+(.+?)(?:\n|$)", endings_text):
        endings.append(m.group(1).strip())
    return endings


def _extract_performer_name(section: str) -> str:
    """Try to extract a performer name from Ren'Py show commands.

    Ren'Py lines look like: show emilie_pole suit → performer is "Emilie".
    """
    m = re.search(r'show\s+([a-z]+)_', section, re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        return name.capitalize()

    # Fallback: look for the stripper name
    m = re.search(r'Name:\s*"([^"]+)"', section)
    if m:
        return m.group(1).strip()

    return ""


def _extract_stripper_info(section: str) -> dict[str, str]:
    """Extract stripper past arc info."""
    arc_text = _extract_between_bold_sections(section, "Stripper Past Arc")
    if not arc_text:
        return {}

    info: dict[str, str] = {}
    for key in ("Club", "Name", "Quit Reason", "Return Trigger", "Unique Kink"):
        m = re.search(rf"{key}:\s*(.+?)(?:\.|$)", arc_text)
        if m:
            info[key.lower().replace(" ", "_")] = m.group(1).strip()
    return info


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------

def load_queens() -> list[QueenProfile]:
    """Parse the Master Document and return all queen profiles.

    The document uses **Profile N** bold markers for each queen.
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

    # Split on **Profile N** markers (the document uses bold, not markdown headings)
    profile_sections = re.split(
        r"(?=\*\*Profile\s+\d+\*\*)", content
    )

    queens: list[QueenProfile] = []

    for section in profile_sections:
        if not section.strip():
            continue

        # Verify this section starts with a **Profile N** header
        header_match = re.match(r"\*\*Profile\s+(\d+)\*\*", section)
        if not header_match:
            continue

        profile_num = int(header_match.group(1))
        queen_id = f"queen-{profile_num:02d}"

        # Try to extract performer name from Ren'Py code
        performer_ref = _extract_performer_name(section)

        # Use "Queen N" as the display name, with performer ref if available
        name = f"Queen {profile_num}"
        if performer_ref:
            name = f"Queen {profile_num} ({performer_ref})"

        # Extract physical blueprint
        blueprint = _parse_physical_blueprint(section)

        # Extract DNA traits from the table
        dna_traits = _parse_dna_table(section)
        dna = QueenDNA(**dna_traits) if dna_traits else QueenDNA()

        # Extract Flux portrait prompt
        portrait_prompt = _extract_flux_prompt(section)

        # Extract scenes
        scenes = _extract_scenes(section)

        # Extract endings (store in blueprint for now)
        endings = _extract_endings(section)
        if endings:
            blueprint["endings"] = endings

        # Stripper arc info
        stripper_info = _extract_stripper_info(section)
        if stripper_info:
            blueprint["stripper_arc"] = stripper_info

        # Check for trained LoRA
        lora_match = re.search(
            r"lora\s*[:=]\s*(.+\.safetensors)", section, re.IGNORECASE
        )
        lora_name = lora_match.group(1).strip() if lora_match else None

        # Check for reference images on VAULT
        ref_slug = _slugify(performer_ref) if performer_ref else queen_id
        ref_dir = Path(PERFORMER_REFS_PATH) / ref_slug
        ref_images: list[str] = []
        if ref_dir.exists():
            ref_images = [
                f.name for f in ref_dir.iterdir()
                if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
            ]

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
        logger.debug(
            "  Profile %d: %s — %d scenes, %d DNA traits, prompt=%s",
            profile_num, performer_ref or "unknown",
            len(scenes), len(dna_traits),
            "yes" if portrait_prompt else "no",
        )

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
