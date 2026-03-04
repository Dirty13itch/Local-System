"""DNA-to-Prompt Engine — converts 19-trait queen profiles into visual modifiers.

Maps trait combinations to lighting, mood, pose, expression, and environment
descriptors that get appended to Flux generation prompts.
"""

from __future__ import annotations


# Threshold for "high" trait activation
HIGH = 7
LOW = 4


def dna_to_prompt_modifiers(traits: dict[str, int]) -> str:
    """Convert a queen's 19-trait DNA profile into prompt style modifiers.

    Takes a dict of trait_name -> score (1-10) and returns a comma-separated
    string of visual/mood descriptors suitable for appending to a Flux prompt.

    Trait Definitions:
        dominance, submission, exhibitionism, voyeurism, nurturing, corruption,
        possessiveness, devotion, playfulness, intensity, ritualism, spontaneity,
        emotional_openness, guardedness, sensory_focus, intellectual_arousal,
        power_exchange, intimacy_threshold, taboo_comfort
    """
    modifiers: list[str] = []

    d = {k.lower().replace(" ", "_"): v for k, v in traits.items()}

    # --- Dominant archetype ---
    if d.get("dominance", 5) >= HIGH and d.get("intensity", 5) >= HIGH:
        modifiers.append("commanding presence, piercing gaze, powerful stance")
    elif d.get("dominance", 5) >= HIGH:
        modifiers.append("confident authority, strong posture, direct eye contact")

    # --- Submissive archetype ---
    if d.get("submission", 5) >= HIGH and d.get("devotion", 5) >= HIGH:
        modifiers.append("soft gaze, vulnerable beauty, gentle surrender")
    elif d.get("submission", 5) >= HIGH:
        modifiers.append("demure expression, lowered eyes, graceful poise")

    # --- Exhibitionist energy ---
    if d.get("exhibitionism", 5) >= HIGH and d.get("playfulness", 5) >= HIGH:
        modifiers.append("confident smirk, teasing pose, playful energy")
    elif d.get("exhibitionism", 5) >= HIGH:
        modifiers.append("bold presence, unapologetic beauty, proud stance")

    # --- Dark allure ---
    if d.get("corruption", 5) >= HIGH and d.get("taboo_comfort", 5) >= HIGH:
        modifiers.append("dark allure, forbidden beauty, sinful elegance")
    elif d.get("corruption", 5) >= HIGH:
        modifiers.append("mysterious edge, dangerous beauty, shadowed glamour")

    # --- Nurturing warmth ---
    if d.get("nurturing", 5) >= HIGH and d.get("emotional_openness", 5) >= HIGH:
        modifiers.append("warm smile, inviting eyes, maternal glow")
    elif d.get("nurturing", 5) >= HIGH:
        modifiers.append("gentle warmth, caring expression, soft lighting")

    # --- Power exchange dynamics ---
    if d.get("power_exchange", 5) >= HIGH:
        modifiers.append("dynamic tension, electric energy, charged atmosphere")

    # --- Intellectual seduction ---
    if d.get("intellectual_arousal", 5) >= HIGH and d.get("guardedness", 5) >= HIGH:
        modifiers.append("knowing look, calculated elegance, enigmatic smile")
    elif d.get("intellectual_arousal", 5) >= HIGH:
        modifiers.append("thoughtful gaze, refined beauty, cerebral intensity")

    # --- Sensory richness ---
    if d.get("sensory_focus", 5) >= HIGH:
        modifiers.append("rich textures, dramatic lighting, tactile warmth")

    # --- Ritualistic presence ---
    if d.get("ritualism", 5) >= HIGH:
        modifiers.append("ceremonial poise, deliberate grace, sacred atmosphere")

    # --- Spontaneous vitality ---
    if d.get("spontaneity", 5) >= HIGH and d.get("playfulness", 5) >= HIGH:
        modifiers.append("natural energy, candid joy, vibrant motion")
    elif d.get("spontaneity", 5) >= HIGH:
        modifiers.append("organic movement, authentic moment, unposed beauty")

    # --- Possessive intensity ---
    if d.get("possessiveness", 5) >= HIGH and d.get("intensity", 5) >= HIGH:
        modifiers.append("fierce devotion, burning eyes, consuming presence")

    # --- High intimacy threshold = distant/untouchable ---
    if d.get("intimacy_threshold", 5) >= HIGH:
        modifiers.append("untouchable beauty, regal distance, statuesque poise")
    elif d.get("intimacy_threshold", 5) <= LOW:
        modifiers.append("approachable warmth, intimate closeness, inviting gaze")

    # --- Voyeuristic quality ---
    if d.get("voyeurism", 5) >= HIGH:
        modifiers.append("observant eyes, quiet intensity, watching presence")

    # --- Lighting based on overall mood ---
    intensity = d.get("intensity", 5)
    corruption = d.get("corruption", 5)
    nurturing = d.get("nurturing", 5)

    if corruption >= HIGH and intensity >= HIGH:
        modifiers.append("dramatic chiaroscuro lighting, deep shadows")
    elif nurturing >= HIGH:
        modifiers.append("warm golden hour lighting, soft ambient glow")
    elif intensity >= HIGH:
        modifiers.append("high contrast lighting, cinematic atmosphere")

    return ", ".join(modifiers) if modifiers else "natural beauty, elegant pose"
