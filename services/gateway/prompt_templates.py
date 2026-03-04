"""Prompt Template Library — pre-built generation presets for common scenarios.

Each template provides a base prompt with a {subject} placeholder that gets
filled with the character/person description. Templates include suggested
pipeline, dimensions, negative prompt, and metadata.

Categories:
    intimate_portrait: Bedroom, lingerie, soft lighting
    glamour: Pin-up, fashion, artistic nude
    explicit_scene: Various explicit scenario templates
    character_portrait: Standard queen/character portraits
"""

from __future__ import annotations

from typing import Any


class PromptTemplate:
    """A pre-built prompt template for quick generation."""

    def __init__(
        self,
        id: str,
        name: str,
        category: str,
        base_prompt: str,
        negative_prompt: str,
        pipeline: str = "flux-uncensored",
        width: int = 1024,
        height: int = 1024,
        steps: int = 25,
        cfg: float = 1.0,
        restore_face: bool = True,
        tags: list[str] | None = None,
    ):
        self.id = id
        self.name = name
        self.category = category
        self.base_prompt = base_prompt
        self.negative_prompt = negative_prompt
        self.pipeline = pipeline
        self.width = width
        self.height = height
        self.steps = steps
        self.cfg = cfg
        self.restore_face = restore_face
        self.tags = tags or []

    def fill(self, subject: str = "beautiful woman", **extra: str) -> str:
        """Fill the template with a subject description."""
        prompt = self.base_prompt.replace("{subject}", subject)
        for key, val in extra.items():
            prompt = prompt.replace(f"{{{key}}}", val)
        return prompt

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "base_prompt": self.base_prompt,
            "negative_prompt": self.negative_prompt,
            "pipeline": self.pipeline,
            "width": self.width,
            "height": self.height,
            "steps": self.steps,
            "cfg": self.cfg,
            "restore_face": self.restore_face,
            "tags": self.tags,
        }


# Default negative prompt for photorealistic NSFW
_NEG_PHOTO = (
    "blurry, low quality, deformed, ugly, bad anatomy, disfigured, "
    "poorly drawn face, mutation, extra limb, poorly drawn hands, "
    "watermark, text, logo, cartoon, 3d render, anime, illustration"
)

_NEG_EXPLICIT = (
    f"{_NEG_PHOTO}, censored, mosaic, black bars, pixelated"
)


# ---------------------------------------------------------------------------
# Template Definitions
# ---------------------------------------------------------------------------

PROMPT_TEMPLATES: dict[str, PromptTemplate] = {}


def _register(t: PromptTemplate) -> PromptTemplate:
    PROMPT_TEMPLATES[t.id] = t
    return t


# ── Character Portraits ──────────────────────────────────────────────────

_register(PromptTemplate(
    id="portrait-studio",
    name="Studio Portrait",
    category="character_portrait",
    base_prompt=(
        "hyperrealistic studio portrait of {subject}, "
        "professional photography, softbox lighting, shallow depth of field, "
        "clean background, sharp focus, masterpiece, best quality, 8K UHD"
    ),
    negative_prompt=_NEG_PHOTO,
    width=832, height=1216,
    tags=["portrait", "studio", "headshot"],
))

_register(PromptTemplate(
    id="portrait-cinematic",
    name="Cinematic Portrait",
    category="character_portrait",
    base_prompt=(
        "cinematic portrait of {subject}, "
        "dramatic rim lighting, film grain, anamorphic bokeh, "
        "movie still, professional color grading, masterpiece, 8K"
    ),
    negative_prompt=_NEG_PHOTO,
    width=832, height=1216,
    tags=["portrait", "cinematic", "dramatic"],
))

_register(PromptTemplate(
    id="portrait-natural",
    name="Natural Light Portrait",
    category="character_portrait",
    base_prompt=(
        "natural light portrait of {subject}, "
        "golden hour sunlight, outdoor setting, warm tones, "
        "candid moment, soft focus background, masterpiece, best quality"
    ),
    negative_prompt=_NEG_PHOTO,
    width=832, height=1216,
    tags=["portrait", "natural", "outdoor"],
))

# ── Intimate Portraits ───────────────────────────────────────────────────

_register(PromptTemplate(
    id="intimate-bedroom",
    name="Bedroom Intimate",
    category="intimate_portrait",
    base_prompt=(
        "intimate bedroom portrait of {subject}, "
        "lying on silk sheets, soft warm lamplight, "
        "lace lingerie, relaxed pose, bedroom eyes, "
        "shallow depth of field, warm color palette, masterpiece, 8K UHD"
    ),
    negative_prompt=_NEG_EXPLICIT,
    width=832, height=1216,
    tags=["intimate", "bedroom", "lingerie"],
))

_register(PromptTemplate(
    id="intimate-boudoir",
    name="Boudoir Shoot",
    category="intimate_portrait",
    base_prompt=(
        "professional boudoir photography of {subject}, "
        "sheer robe falling off shoulder, sitting on chaise lounge, "
        "soft diffused lighting, elegant and sensual, "
        "high fashion boudoir, masterpiece, best quality, 8K"
    ),
    negative_prompt=_NEG_EXPLICIT,
    width=832, height=1216,
    tags=["intimate", "boudoir", "elegant"],
))

_register(PromptTemplate(
    id="intimate-bath",
    name="Bath Scene",
    category="intimate_portrait",
    base_prompt=(
        "sensual bath scene, {subject} in luxurious bathtub, "
        "candlelight, rose petals, steam, wet skin glistening, "
        "soft warm lighting, relaxed expression, "
        "masterpiece, best quality, hyperrealistic, 8K"
    ),
    negative_prompt=_NEG_EXPLICIT,
    width=1344, height=768,
    tags=["intimate", "bath", "water"],
))

_register(PromptTemplate(
    id="intimate-morning",
    name="Morning After",
    category="intimate_portrait",
    base_prompt=(
        "morning light portrait of {subject}, "
        "lying in rumpled white sheets, natural morning sunlight, "
        "messy hair, bare shoulders, sleepy seductive expression, "
        "intimate close-up, warm tones, masterpiece, 8K"
    ),
    negative_prompt=_NEG_EXPLICIT,
    width=1344, height=768,
    tags=["intimate", "morning", "natural"],
))

# ── Glamour / Pin-up ─────────────────────────────────────────────────────

_register(PromptTemplate(
    id="glamour-pinup",
    name="Classic Pin-Up",
    category="glamour",
    base_prompt=(
        "classic pin-up style photograph of {subject}, "
        "retro swimsuit, playful pose, winking, "
        "vintage studio backdrop, vibrant colors, "
        "1950s glamour photography, masterpiece, best quality, 8K"
    ),
    negative_prompt=_NEG_PHOTO,
    width=832, height=1216,
    tags=["glamour", "pinup", "retro"],
))

_register(PromptTemplate(
    id="glamour-pool",
    name="Poolside Glamour",
    category="glamour",
    base_prompt=(
        "glamour poolside photograph of {subject}, "
        "bikini, wet skin, sunlight reflections, "
        "luxury pool setting, tropical backdrop, "
        "fashion photography, masterpiece, 8K UHD"
    ),
    negative_prompt=_NEG_EXPLICIT,
    width=1344, height=768,
    tags=["glamour", "pool", "bikini", "outdoor"],
))

_register(PromptTemplate(
    id="glamour-artistic",
    name="Artistic Nude",
    category="glamour",
    base_prompt=(
        "artistic nude photography of {subject}, "
        "abstract lighting, dramatic shadows across body, "
        "black and white, fine art photography, museum quality, "
        "tasteful composition, masterpiece, best quality, 8K"
    ),
    negative_prompt=_NEG_EXPLICIT,
    width=832, height=1216,
    tags=["glamour", "artistic", "nude", "fine-art"],
))

# ── Explicit Scenes ──────────────────────────────────────────────────────

_register(PromptTemplate(
    id="explicit-solo-bed",
    name="Solo Bedroom",
    category="explicit_scene",
    base_prompt=(
        "explicit photograph of {subject}, nude on bed, "
        "legs spread, touching herself, ecstatic expression, "
        "bedroom setting, warm lamplight, rumpled sheets, "
        "sweat glistening on skin, hyperrealistic, masterpiece, 8K UHD"
    ),
    negative_prompt=_NEG_EXPLICIT,
    width=1344, height=768,
    tags=["explicit", "solo", "bedroom", "nude"],
))

_register(PromptTemplate(
    id="explicit-solo-shower",
    name="Solo Shower",
    category="explicit_scene",
    base_prompt=(
        "explicit photograph of {subject}, nude in glass shower, "
        "water cascading over body, wet hair, steamy glass, "
        "hands sliding over wet skin, aroused expression, "
        "studio lighting through steam, hyperrealistic, masterpiece, 8K"
    ),
    negative_prompt=_NEG_EXPLICIT,
    width=832, height=1216,
    tags=["explicit", "solo", "shower", "wet"],
))

_register(PromptTemplate(
    id="explicit-strip",
    name="Striptease",
    category="explicit_scene",
    base_prompt=(
        "explicit photograph of {subject}, mid-striptease, "
        "pulling down panties, teasing expression, "
        "standing in heels, strip club stage lighting, "
        "pole behind, spotlight, hyperrealistic, masterpiece, 8K"
    ),
    negative_prompt=_NEG_EXPLICIT,
    width=832, height=1216,
    tags=["explicit", "strip", "tease", "pole"],
))

_register(PromptTemplate(
    id="explicit-dom",
    name="Dominant Pose",
    category="explicit_scene",
    base_prompt=(
        "explicit photograph of {subject}, dominant pose, "
        "leather lingerie, standing with legs apart, "
        "hands on hips, commanding stare, collar and leash in hand, "
        "dark moody lighting, hyperrealistic, masterpiece, 8K"
    ),
    negative_prompt=_NEG_EXPLICIT,
    width=832, height=1216,
    tags=["explicit", "dominant", "leather", "bdsm"],
))

_register(PromptTemplate(
    id="explicit-sub",
    name="Submissive Pose",
    category="explicit_scene",
    base_prompt=(
        "explicit photograph of {subject}, submissive pose, "
        "kneeling nude, hands behind back, looking up, "
        "collar around neck, soft expression, vulnerable beauty, "
        "dramatic lighting from above, hyperrealistic, masterpiece, 8K"
    ),
    negative_prompt=_NEG_EXPLICIT,
    width=832, height=1216,
    tags=["explicit", "submissive", "kneeling", "bdsm"],
))

_register(PromptTemplate(
    id="explicit-spread",
    name="Open Legs",
    category="explicit_scene",
    base_prompt=(
        "explicit photograph of {subject}, sitting nude on chair, "
        "legs wide open, leaning back, seductive expression, "
        "direct eye contact with camera, full body visible, "
        "professional studio lighting, hyperrealistic, masterpiece, 8K"
    ),
    negative_prompt=_NEG_EXPLICIT,
    width=1344, height=768,
    tags=["explicit", "spread", "nude", "frontal"],
))

_register(PromptTemplate(
    id="explicit-rear",
    name="From Behind",
    category="explicit_scene",
    base_prompt=(
        "explicit photograph of {subject}, nude rear view, "
        "on all fours on bed, looking back over shoulder, "
        "arched back, seductive expression, "
        "warm bedroom lighting, hyperrealistic, masterpiece, 8K"
    ),
    negative_prompt=_NEG_EXPLICIT,
    width=1344, height=768,
    tags=["explicit", "rear", "nude", "behind"],
))


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def list_templates(category: str | None = None) -> list[dict]:
    """Return all templates, optionally filtered by category."""
    templates = PROMPT_TEMPLATES.values()
    if category:
        templates = [t for t in templates if t.category == category]
    return [t.to_dict() for t in templates]


def get_template(template_id: str) -> PromptTemplate | None:
    """Get a specific template by ID."""
    return PROMPT_TEMPLATES.get(template_id)


def fill_template(
    template_id: str,
    subject: str = "beautiful woman",
    **extra: str,
) -> dict | None:
    """Fill a template and return generation params ready to submit."""
    t = PROMPT_TEMPLATES.get(template_id)
    if not t:
        return None

    return {
        "prompt": t.fill(subject, **extra),
        "negative_prompt": t.negative_prompt,
        "pipeline": t.pipeline,
        "width": t.width,
        "height": t.height,
        "steps": t.steps,
        "cfg": t.cfg,
        "restore_face": t.restore_face,
    }
