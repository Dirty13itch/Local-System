"""DNA-to-Prompt Engine — converts 19-trait queen profiles into visual modifiers.

Maps trait combinations to lighting, mood, pose, expression, and environment
descriptors that get appended to Flux generation prompts.

Two modes:
    - Aesthetic (default): Portrait photography descriptors — lighting, mood, gaze
    - Explicit (explicit=True): NSFW scene descriptors — body positioning, clothing
      state, expression intensity, physical interaction keywords
"""

from __future__ import annotations


# Threshold for "high" trait activation
HIGH = 7
LOW = 4


def dna_to_prompt_modifiers(traits: dict[str, int], explicit: bool = False) -> str:
    """Convert a queen's 19-trait DNA profile into prompt style modifiers.

    Takes a dict of trait_name -> score (1-10) and returns a comma-separated
    string of visual/mood descriptors suitable for appending to a Flux prompt.

    Args:
        traits: Dict of trait_name -> score (1-10).
        explicit: If True, generates NSFW-specific modifiers for body positioning,
                  clothing state, expression intensity, and explicit scene tags
                  in addition to aesthetic modifiers.

    Trait Definitions:
        dominance, submission, exhibitionism, voyeurism, nurturing, corruption,
        possessiveness, devotion, playfulness, intensity, ritualism, spontaneity,
        emotional_openness, guardedness, sensory_focus, intellectual_arousal,
        power_exchange, intimacy_threshold, taboo_comfort
    """
    modifiers: list[str] = []

    d = {k.lower().replace(" ", "_"): v for k, v in traits.items()}

    # ── Aesthetic modifiers (always applied) ──────────────────────────────

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

    # ── Explicit modifiers (NSFW mode) ────────────────────────────────────

    if explicit:
        modifiers.extend(_explicit_modifiers(d))

    return ", ".join(modifiers) if modifiers else "natural beauty, elegant pose"


def _explicit_modifiers(d: dict[str, int]) -> list[str]:
    """Generate NSFW-specific modifiers based on DNA trait combinations.

    Maps traits to: clothing state, body positioning, expression intensity,
    skin detail, and explicit scene descriptors.
    """
    mods: list[str] = []

    # ── Clothing state (driven by exhibitionism + taboo_comfort) ─────────
    exhib = d.get("exhibitionism", 5)
    taboo = d.get("taboo_comfort", 5)
    playful = d.get("playfulness", 5)

    if exhib >= 9 and taboo >= 8:
        mods.append("fully nude, completely naked, bare skin")
    elif exhib >= HIGH and taboo >= HIGH:
        mods.append("nude, naked body, exposed skin")
    elif exhib >= HIGH:
        mods.append("topless, sheer lingerie, barely covered")
    elif exhib >= 5:
        mods.append("revealing lingerie, lace bra, sheer fabric")
    else:
        mods.append("partially unbuttoned, suggestive clothing, hint of skin")

    # ── Body positioning (driven by submission/dominance + intensity) ─────
    dom = d.get("dominance", 5)
    sub = d.get("submission", 5)
    intensity = d.get("intensity", 5)
    devotion = d.get("devotion", 5)

    if sub >= HIGH and devotion >= HIGH:
        mods.append("kneeling pose, head tilted back, arched back, submissive position")
    elif sub >= HIGH:
        mods.append("on knees, looking up, hands behind back, vulnerable pose")
    elif dom >= HIGH and intensity >= HIGH:
        mods.append("standing over viewer, legs apart, hands on hips, dominant pose")
    elif dom >= HIGH:
        mods.append("confident spread, leaning forward, assertive body language")
    elif playful >= HIGH:
        mods.append("playful pose, lying on bed, legs crossed, flirtatious position")
    else:
        mods.append("natural pose, relaxed position, candid angle")

    # ── Expression intensity (driven by sensory_focus + intensity) ────────
    sensory = d.get("sensory_focus", 5)
    emotional = d.get("emotional_openness", 5)

    if sensory >= HIGH and intensity >= HIGH:
        mods.append("ecstatic expression, lips parted, heavy-lidded eyes, flushed skin")
    elif sensory >= HIGH:
        mods.append("aroused expression, parted lips, half-closed eyes, pleasure")
    elif emotional >= HIGH:
        mods.append("intimate expression, bedroom eyes, soft moan, desire")
    elif intensity >= HIGH:
        mods.append("intense expression, fierce desire, passionate gaze")
    else:
        mods.append("seductive expression, knowing smile, inviting look")

    # ── Skin detail (driven by sensory_focus) ────────────────────────────
    if sensory >= HIGH:
        mods.append("detailed skin texture, visible pores, natural skin imperfections")
        mods.append("sweat glistening on skin, body moisture, wet skin highlights")

    # ── Power dynamics scene cues ────────────────────────────────────────
    power = d.get("power_exchange", 5)
    corruption = d.get("corruption", 5)
    ritualism = d.get("ritualism", 5)

    if power >= HIGH and corruption >= HIGH:
        mods.append("leather accessories, collar, restraint marks")
    elif power >= HIGH:
        mods.append("power dynamic, tension between partners, charged touch")

    if ritualism >= HIGH and corruption >= HIGH:
        mods.append("candle wax, dim candlelight, ritual atmosphere")
    elif ritualism >= HIGH:
        mods.append("deliberate placement, posed arrangement, intentional staging")

    # ── Voyeur framing ───────────────────────────────────────────────────
    voyeur = d.get("voyeurism", 5)
    if voyeur >= HIGH:
        mods.append("caught unaware angle, through doorway perspective, voyeuristic framing")

    # ── Spontaneity vs staged ────────────────────────────────────────────
    spont = d.get("spontaneity", 5)
    if spont >= HIGH:
        mods.append("caught in the moment, spontaneous undressing, natural movement")

    # ── Intimacy closeness ───────────────────────────────────────────────
    intimacy = d.get("intimacy_threshold", 5)
    if intimacy <= LOW:
        mods.append("extreme close-up, intimate camera angle, personal space invasion")
    elif intimacy >= HIGH:
        mods.append("full body shot, observational distance, composed framing")

    return mods
