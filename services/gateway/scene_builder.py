"""Scene Prompt Builder — constructs detailed Flux prompts from queen data.

Replaces the naive "portrait_prompt + scene_title" concatenation with
proper prompts built from the queen's physical blueprint, DNA modifiers,
and scene description. Produces both portrait and scene prompts.
"""

from __future__ import annotations

from local_system.models import QueenProfile
from .dna_engine import dna_to_prompt_modifiers


# Quality tags appended to every prompt
QUALITY_SUFFIX = (
    "masterpiece, best quality, ultra detailed, hyperrealistic, "
    "8K UHD, photorealistic, professional photography, "
    "sharp focus, high resolution, RAW photo"
)

# Standard negative prompt for photorealistic generation
DEFAULT_NEGATIVE = (
    "blurry, low quality, deformed, ugly, bad anatomy, disfigured, "
    "poorly drawn face, mutation, mutated, extra limb, poorly drawn hands, "
    "missing limb, floating limbs, disconnected limbs, malformed hands, "
    "long neck, long body, disgusting, watermark, text, logo, "
    "cartoon, 3d render, anime, illustration, painting"
)


def _physical_description(queen: QueenProfile) -> str:
    """Build a physical appearance description from the queen's blueprint."""
    bp = queen.physical_blueprint
    if not bp:
        return "beautiful woman"

    parts: list[str] = []

    # Core body description
    body_type = bp.get("body_type", "")
    if body_type:
        parts.append(f"{body_type} body type")

    height = bp.get("height", "")
    if height:
        parts.append(height)

    # Face
    face_shape = bp.get("face_shape", "")
    if face_shape:
        parts.append(f"{face_shape} face")

    eyes = bp.get("eyes", "")
    if eyes:
        parts.append(f"{eyes} eyes")

    # Hair
    hair = bp.get("hair", "")
    if hair:
        parts.append(f"{hair} hair")

    # Skin
    skin = bp.get("skin", "")
    if skin:
        parts.append(f"{skin} skin")

    # Measurements and bust for explicit mode
    measurements = bp.get("measurements", "")
    bra_cup = bp.get("bra_cup", "")
    if bra_cup:
        parts.append(f"{bra_cup} bust")
    elif measurements:
        parts.append(f"{measurements} measurements")

    # Key trait
    key_trait = bp.get("key_prime_trait", "")
    if key_trait:
        parts.append(key_trait)

    return ", ".join(parts) if parts else "beautiful woman"


def build_portrait_prompt(
    queen: QueenProfile,
    explicit: bool = False,
) -> str:
    """Build a detailed portrait prompt from a queen's profile.

    Uses the queen's existing Flux portrait prompt as a base and enhances it
    with physical blueprint details and DNA modifiers.

    Args:
        queen: The queen profile to build a prompt for.
        explicit: If True, uses explicit DNA modifiers and NSFW descriptors.
    """
    # Start with the queen's authored Flux prompt if available
    base = queen.flux_portrait_prompt
    if not base:
        phys = _physical_description(queen)
        base = f"hyperrealistic portrait of a {phys}, professional studio photography"

    # DNA modifiers (explicit or aesthetic)
    dna_dict = queen.dna.model_dump()
    dna_mods = dna_to_prompt_modifiers(dna_dict, explicit=explicit)

    # Compose final prompt
    parts = [base]
    if dna_mods:
        parts.append(dna_mods)
    parts.append(QUALITY_SUFFIX)

    return ", ".join(parts)


def build_scene_prompt(
    queen: QueenProfile,
    scene_index: int,
    explicit: bool = True,
) -> str:
    """Build a detailed scene prompt from a queen's profile and scene data.

    Combines the queen's physical description, scene context, and DNA-derived
    mood/pose modifiers into a comprehensive Flux generation prompt.

    Args:
        queen: The queen profile containing physical blueprint and DNA.
        scene_index: Index into queen.scenes list.
        explicit: If True (default), uses explicit DNA modifiers for NSFW output.

    Returns:
        A complete Flux prompt string optimized for the scene.
    """
    # Validate scene index
    if scene_index < 0 or scene_index >= len(queen.scenes):
        # Fall back to portrait prompt
        return build_portrait_prompt(queen, explicit=explicit)

    scene = queen.scenes[scene_index]

    # Physical description of the character
    phys = _physical_description(queen)

    # Scene description from the Master Document
    scene_desc = scene.description or scene.title

    # Build the core prompt: character + scene context
    parts: list[str] = []
    parts.append(f"cinematic widescreen scene, {phys}")

    # Scene context — use the description to set the scenario
    if scene_desc:
        parts.append(f"scene: {scene_desc}")

    # DNA modifiers for mood, pose, expression, and explicit content
    dna_dict = queen.dna.model_dump()
    dna_mods = dna_to_prompt_modifiers(dna_dict, explicit=explicit)
    if dna_mods:
        parts.append(dna_mods)

    # Quality and format tags
    parts.append("cinematic composition, dramatic lighting, film grain")
    parts.append(QUALITY_SUFFIX)

    return ", ".join(parts)


def build_scene_negative(explicit: bool = True) -> str:
    """Return the standard negative prompt, optionally with explicit additions."""
    neg = DEFAULT_NEGATIVE
    if explicit:
        # For explicit content we want to avoid censoring artifacts
        neg += ", censored, mosaic, black bars, pixelated"
    return neg
