"""Feedback storage — ratings and style preferences for steering autonomous generation.

Single-user system — stores everything in a JSON file on VAULT NFS.
No database needed. Loaded into memory on startup, written on every change.

Storage location: gen-refs/.feedback.json (alongside manifests)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger("gateway.feedback")

# Storage path — next to ref manifests on VAULT NFS
REFS_DIR = Path(os.environ.get("GEN_REFS_DIR", "/mnt/vault/data/gen-refs"))
FEEDBACK_FILE = REFS_DIR / ".feedback.json"


@dataclass
class ImageRating:
    """A single image rating."""
    subject: str
    filename: str
    rating: str  # "good" | "bad"
    prompt: str = ""
    notes: str = ""
    timestamp: str = ""


@dataclass
class StylePreferences:
    """User's style preferences — free-text steering notes."""
    like_more: str = ""   # "more dramatic lighting, more outdoor scenes"
    like_less: str = ""   # "less studio shots, less close-ups"
    body_notes: str = ""  # "prefer athletic builds, toned"
    mood_notes: str = ""  # "prefer confident, intense expressions"
    setting_notes: str = ""  # "prefer natural environments, golden hour"
    custom: str = ""      # freeform notes


@dataclass
class FeedbackStore:
    """Persisted feedback data."""
    ratings: dict[str, ImageRating] = field(default_factory=dict)
    preferences: StylePreferences = field(default_factory=StylePreferences)
    total_rated: int = 0
    total_good: int = 0
    total_bad: int = 0


class FeedbackManager:
    """Manages image ratings and style preferences.

    Provides:
      - rate_image(): Store a good/bad rating for a generated image
      - get_ratings(): Get all ratings, optionally filtered by subject
      - update_preferences(): Update style preferences
      - get_prompt_context(): Generate a context block for LLM prompt injection
      - summary(): Stats overview
    """

    def __init__(self, feedback_file: Path = FEEDBACK_FILE):
        self._file = feedback_file
        self._store = FeedbackStore()
        self._load()

    def _load(self):
        """Load feedback from disk."""
        if not self._file.exists():
            logger.info("No feedback file found, starting fresh")
            return

        try:
            data = json.loads(self._file.read_text())
            # Restore ratings
            for key, r in data.get("ratings", {}).items():
                self._store.ratings[key] = ImageRating(**r)
            # Restore preferences
            prefs = data.get("preferences", {})
            if prefs:
                self._store.preferences = StylePreferences(**prefs)
            # Restore stats
            self._store.total_rated = data.get("total_rated", 0)
            self._store.total_good = data.get("total_good", 0)
            self._store.total_bad = data.get("total_bad", 0)

            logger.info(
                "Loaded feedback: %d ratings (%d good, %d bad), preferences active: %s",
                self._store.total_rated,
                self._store.total_good,
                self._store.total_bad,
                bool(self._store.preferences.like_more or self._store.preferences.like_less),
            )
        except Exception as e:
            logger.warning("Failed to load feedback file: %s", e)

    def _save(self):
        """Persist feedback to disk."""
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "ratings": {k: asdict(v) for k, v in self._store.ratings.items()},
                "preferences": asdict(self._store.preferences),
                "total_rated": self._store.total_rated,
                "total_good": self._store.total_good,
                "total_bad": self._store.total_bad,
            }
            self._file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error("Failed to save feedback: %s", e)

    def _rating_key(self, subject: str, filename: str) -> str:
        return f"{subject}/{filename}"

    # ─── Public API ──────────────────────────────────────────────────

    def rate_image(
        self,
        subject: str,
        filename: str,
        rating: str,
        prompt: str = "",
        notes: str = "",
    ) -> ImageRating:
        """Rate an image as good or bad.

        If the image was already rated, the previous rating is replaced.
        """
        if rating not in ("good", "bad"):
            raise ValueError(f"Rating must be 'good' or 'bad', got '{rating}'")

        key = self._rating_key(subject, filename)

        # Check if re-rating — adjust counts
        old = self._store.ratings.get(key)
        if old:
            if old.rating == "good":
                self._store.total_good -= 1
            else:
                self._store.total_bad -= 1
            self._store.total_rated -= 1

        entry = ImageRating(
            subject=subject,
            filename=filename,
            rating=rating,
            prompt=prompt,
            notes=notes,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        self._store.ratings[key] = entry

        self._store.total_rated += 1
        if rating == "good":
            self._store.total_good += 1
        else:
            self._store.total_bad += 1

        self._save()
        logger.info("Rated %s/%s as %s", subject, filename, rating)
        return entry

    def remove_rating(self, subject: str, filename: str) -> bool:
        """Remove a rating (unrate)."""
        key = self._rating_key(subject, filename)
        old = self._store.ratings.pop(key, None)
        if old:
            self._store.total_rated -= 1
            if old.rating == "good":
                self._store.total_good -= 1
            else:
                self._store.total_bad -= 1
            self._save()
            return True
        return False

    def get_rating(self, subject: str, filename: str) -> ImageRating | None:
        """Get the rating for a specific image."""
        return self._store.ratings.get(self._rating_key(subject, filename))

    def get_ratings(
        self,
        subject: str | None = None,
        rating_filter: str | None = None,
    ) -> list[dict]:
        """Get ratings, optionally filtered by subject and/or rating value."""
        results = []
        for key, r in self._store.ratings.items():
            if subject and r.subject != subject:
                continue
            if rating_filter and r.rating != rating_filter:
                continue
            results.append(asdict(r))
        return results

    def get_all_ratings_map(self) -> dict[str, str]:
        """Get a flat map of 'subject/filename' → 'good'/'bad' for the gallery UI."""
        return {k: v.rating for k, v in self._store.ratings.items()}

    def update_preferences(self, **kwargs) -> StylePreferences:
        """Update style preferences. Only non-None kwargs are applied."""
        prefs = self._store.preferences
        for field_name in ("like_more", "like_less", "body_notes", "mood_notes", "setting_notes", "custom"):
            if field_name in kwargs and kwargs[field_name] is not None:
                setattr(prefs, field_name, kwargs[field_name])
        self._save()
        logger.info("Updated preferences: %s", {k: v for k, v in kwargs.items() if v is not None})
        return prefs

    def get_preferences(self) -> dict:
        """Get current style preferences."""
        return asdict(self._store.preferences)

    def summary(self) -> dict:
        """Get feedback summary stats."""
        return {
            "total_rated": self._store.total_rated,
            "total_good": self._store.total_good,
            "total_bad": self._store.total_bad,
            "preferences_active": bool(
                self._store.preferences.like_more
                or self._store.preferences.like_less
                or self._store.preferences.body_notes
                or self._store.preferences.mood_notes
                or self._store.preferences.setting_notes
                or self._store.preferences.custom
            ),
        }

    def get_prompt_context(self, subject: str | None = None, max_examples: int = 5) -> str:
        """Generate a context block to inject into the LLM prompt generation.

        This is the core feedback loop — it translates ratings and preferences
        into natural language that steers the creative LLM.

        Returns an empty string if no feedback exists (no-op on first run).
        """
        parts = []
        prefs = self._store.preferences

        # --- Style preferences (most important — direct user intent) ---
        pref_lines = []
        if prefs.like_more:
            pref_lines.append(f"Generate MORE of: {prefs.like_more}")
        if prefs.like_less:
            pref_lines.append(f"Generate LESS of / AVOID: {prefs.like_less}")
        if prefs.body_notes:
            pref_lines.append(f"Body type preference: {prefs.body_notes}")
        if prefs.mood_notes:
            pref_lines.append(f"Mood/expression preference: {prefs.mood_notes}")
        if prefs.setting_notes:
            pref_lines.append(f"Setting/environment preference: {prefs.setting_notes}")
        if prefs.custom:
            pref_lines.append(f"Additional notes: {prefs.custom}")

        if pref_lines:
            parts.append("USER PREFERENCES (follow these closely):\n" + "\n".join(pref_lines))

        # --- Rating-based learning ---
        # Collect good and bad prompts (prefer subject-specific, fall back to global)
        good_prompts = []
        bad_prompts = []
        for _key, r in self._store.ratings.items():
            if not r.prompt:
                continue
            # Subject-specific ratings are weighted first
            is_subject = subject and r.subject == subject
            if r.rating == "good":
                good_prompts.append((r.prompt, is_subject, r.notes))
            else:
                bad_prompts.append((r.prompt, is_subject, r.notes))

        # Sort: subject-specific first, then most recent
        good_prompts.sort(key=lambda x: (not x[1],))
        bad_prompts.sort(key=lambda x: (not x[1],))

        if good_prompts:
            examples = good_prompts[:max_examples]
            lines = [f"  - {p[:200]}" + (f" (note: {n})" if n else "") for p, _, n in examples]
            parts.append(
                f"PROMPTS THE USER LIKED ({self._store.total_good} total good ratings):\n"
                + "\n".join(lines)
                + "\nGenerate prompts with SIMILAR style, lighting, composition, and mood."
            )

        if bad_prompts:
            examples = bad_prompts[:max_examples]
            lines = [f"  - {p[:200]}" + (f" (note: {n})" if n else "") for p, _, n in examples]
            parts.append(
                f"PROMPTS THE USER DISLIKED ({self._store.total_bad} total bad ratings):\n"
                + "\n".join(lines)
                + "\nAVOID generating prompts with similar style, composition, or elements."
            )

        if not parts:
            return ""

        return (
            "\n\n--- USER FEEDBACK (use this to steer your creative choices) ---\n"
            + "\n\n".join(parts)
            + "\n--- END FEEDBACK ---\n"
        )


# ─── Module-level singleton ──────────────────────────────────────────────────
feedback_manager = FeedbackManager()
