"""Auto-generation scheduler — creates drops autonomously on a schedule.

Maintains a library of subjects (reference images) and themes (prompt contexts),
then periodically creates new drops for the auto_gen scanner to process.

Subjects library layout:
  /mnt/vault/data/gen-subjects/
    subjects.json           ← subject definitions + scheduling config
    <subject-name>/         ← reference images for face-ID generation
      ref_01.png
      ref_02.png

Themes are embedded in subjects.json — each subject has a list of theme templates
that get rotated through on each generation cycle.

Usage:
    scheduler = GenScheduler()
    scheduler.start(interval_minutes=120)   # Generate every 2 hours
    scheduler.stop()

    # Or trigger manually:
    await scheduler.create_scheduled_drop()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import shutil
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger("gateway.scheduler")

# Paths
SUBJECTS_DIR = Path(os.environ.get("GEN_SUBJECTS_DIR", "/mnt/vault/data/gen-subjects"))
DROPS_DIR = Path(os.environ.get("GEN_DROPS_DIR", "/mnt/vault/data/gen-drops"))

# Default schedule config
DEFAULT_INTERVAL_MINUTES = 120  # 2 hours between generations
DEFAULT_IMAGES_PER_DROP = 3
DEFAULT_QUIET_HOURS = (2, 7)  # Don't generate between 2am-7am (GPU rest / maintenance window)


# ─── Built-in theme library ─────────────────────────────────────────────────

BUILTIN_THEMES = {
    # ─── Original core themes ──────────────────────────────────────────────
    "portrait-studio": {
        "name": "Studio Portrait",
        "context": "Professional studio portrait, shot on Arri Alexa Mini with 85mm f/1.4, "
                   "dramatic Rembrandt lighting, dark background, sharp focus, shallow depth of field, "
                   "subsurface skin glow, fashion photography, Arri Alexa color science",
        "mode": "explicit",
    },
    "outdoor-golden": {
        "name": "Golden Hour Outdoor",
        "context": "Outdoor portrait during golden hour, shot on Canon EOS R5 with 135mm f/2, "
                   "warm backlit sunlight, lens flare, natural beauty, wind in hair, "
                   "golden skin tones, RAW photo, DaVinci Resolve color grading",
        "mode": "explicit",
    },
    "noir-cinematic": {
        "name": "Film Noir Cinematic",
        "context": "Cinematic film noir style, shot on Arri Alexa Mini with 50mm f/1.2, "
                   "high contrast, dramatic shadows, venetian blind light patterns, "
                   "slight film grain, teal and orange color grading, moody atmosphere",
        "mode": "explicit",
    },
    "fantasy-warrior": {
        "name": "Fantasy Warrior",
        "context": "Epic fantasy warrior portrait, ornate armor barely containing curves, "
                   "dramatic cape, magical volumetric lighting, medieval castle background, "
                   "oil painting quality, subsurface glow on skin, cinematic composition",
        "mode": "explicit",
    },
    "cyberpunk-neon": {
        "name": "Cyberpunk Neon",
        "context": "Cyberpunk neon-lit portrait, futuristic city background, "
                   "holographic reflections on wet skin, rain-slicked streets, "
                   "neon pink and blue rim lighting, shot on Sony A7R IV with 35mm f/1.4",
        "mode": "explicit",
    },
    "bedroom-intimate": {
        "name": "Intimate Bedroom",
        "context": "Intimate bedroom scene, warm candlelight and soft lamplight, silk sheets, "
                   "close-up, shallow depth of field, subsurface skin glow, "
                   "body oil sheen, sweat droplets, heavy-lidded eyes, shot on 85mm f/1.4",
        "mode": "explicit",
    },
    "pool-summer": {
        "name": "Summer Pool",
        "context": "Poolside scene, bright summer day, crystal clear water reflections, "
                   "sun-kissed glistening skin, water droplets on body, tropical setting, "
                   "shot on Canon EOS R5 with 70-200mm f/2.8, natural light",
        "mode": "explicit",
    },
    "gothic-dark": {
        "name": "Gothic Dark",
        "context": "Dark gothic aesthetic, candlelit cathedral, ornate velvet and lace, "
                   "dramatic shadows, moody atmosphere, pale skin contrast against dark fabric, "
                   "volumetric candle smoke, cinematic composition, Arri Alexa color",
        "mode": "explicit",
    },
    "shower-steam": {
        "name": "Steamy Shower",
        "context": "Shower scene, steam rising around body, water cascading down curves, "
                   "wet hair clinging to shoulders, glass door with condensation, "
                   "soft diffused bathroom lighting, glistening skin texture, visible pores",
        "mode": "explicit",
    },
    "office-professional": {
        "name": "Office Professional",
        "context": "Modern executive office, business attire gradually loosened, "
                   "volumetric lighting through floor-to-ceiling windows, city skyline view, "
                   "power pose at mahogany desk, confidence and seduction, Arri Alexa color",
        "mode": "explicit",
    },
    "art-model": {
        "name": "Art Model",
        "context": "Classical art model pose, artist studio, natural light from large windows, "
                   "canvas and paint in background, sculptural nude pose, timeless beauty, "
                   "Rembrandt lighting, subsurface scattering on skin, fine art photography",
        "mode": "explicit",
    },
    "beach-sunset": {
        "name": "Beach Sunset",
        "context": "Beach at sunset, waves breaking in background, warm orange golden hour light, "
                   "sand clinging to wet skin, wind in hair, flowing sheer fabric, "
                   "silhouette rim lighting, shot on 135mm f/2, DaVinci Resolve warm grade",
        "mode": "explicit",
    },

    # ─── EoBQ-inspired scene themes ────────────────────────────────────────
    "neon-club": {
        "name": "Neon Underground Club",
        "context": "Underground strip club scene, red and purple neon lighting, "
                   "dark velvet VIP booth, strobes catching sweat on skin, "
                   "tattoos glowing under blacklight, smoky atmosphere, "
                   "pole visible in background, Arri Alexa color, volumetric haze",
        "mode": "explicit",
    },
    "mirror-room": {
        "name": "Mirror Room Vanity",
        "context": "Luxurious mirror room, infinite reflections of curves from every angle, "
                   "warm vanity lighting, gold-framed mirrors, body admiration pose, "
                   "lingerie or nude, reflections showing different angles simultaneously, "
                   "shot on 50mm f/1.2, shallow depth of field, Arri Alexa color",
        "mode": "explicit",
    },
    "throne-room": {
        "name": "Royal Throne",
        "context": "Regal throne room scene, ornate golden throne, velvet curtains, "
                   "royal dominance pose, legs crossed or draped over armrest, "
                   "crown or tiara, dramatic overhead lighting, marble floor, "
                   "power and seduction, dark luxury aesthetic, cinematic composition",
        "mode": "explicit",
    },
    "helipad-penthouse": {
        "name": "Helipad at Altitude",
        "context": "Private helipad on luxury skyscraper rooftop, 1000ft above city, "
                   "wind whipping hair and sheer fabric, city lights bokeh below, "
                   "dramatic altitude lighting, standing at edge, confidence and power, "
                   "twilight sky gradient, shot on 35mm f/1.4, cinematic widescreen",
        "mode": "explicit",
    },
    "nordic-sauna": {
        "name": "Nordic Sauna Steam",
        "context": "Private Nordic sauna, cedar wood walls, steam rising around naked body, "
                   "sweat beading on pale skin, ice blue eyes through steam, "
                   "warm wooden lighting, fjord visible through frosted window, "
                   "contrasting hot skin and cold environment, intimate atmosphere",
        "mode": "explicit",
    },
    "island-private": {
        "name": "Private Island Sunset",
        "context": "Private tropical island at sunset, olive or golden skin glowing in warm light, "
                   "crystal turquoise water, white sand, palm trees, "
                   "nude on private beach, completely alone, paradise setting, "
                   "golden hour rim lighting, shot on Canon EOS R5 with 85mm f/1.4",
        "mode": "explicit",
    },
    "casino-vip": {
        "name": "Casino VIP High Roller",
        "context": "Las Vegas VIP casino floor, green felt table, scattered chips, "
                   "cocktail dress with plunging neckline, neon casino lighting, "
                   "champagne glass in hand, seductive glance over cards, "
                   "smoky atmosphere, Arri Alexa color, volumetric overhead spotlights",
        "mode": "explicit",
    },
    "pole-performance": {
        "name": "Stage Pole Performance",
        "context": "Professional pole dance stage, chrome pole catching light, "
                   "athletic body mid-spin, strobes and spotlights, platform heels, "
                   "body oil reflecting stage lights, powerful athletic pose, "
                   "sweat glistening, audience darkness beyond stage edge, dramatic lighting",
        "mode": "explicit",
    },
    "executive-surrender": {
        "name": "Boardroom Power Play",
        "context": "Corner executive boardroom, floor-to-ceiling glass walls, city panorama, "
                   "business suit jacket removed revealing lingerie, pencil skirt hiked, "
                   "sitting on boardroom table, legs crossed, power dynamic, "
                   "volumetric office lighting, sharp focus, corporate seduction",
        "mode": "explicit",
    },
    "luxury-bath": {
        "name": "Luxury Marble Bath",
        "context": "Oversized marble bathtub in luxury penthouse, bubble bath, "
                   "candlelight reflecting off wet skin and marble surfaces, "
                   "champagne glass on tub edge, rose petals floating, "
                   "steam and soft focus, warm amber lighting, intimate vulnerability",
        "mode": "explicit",
    },
    "boudoir-silk": {
        "name": "Boudoir Silk & Lace",
        "context": "High-end boudoir photography session, four-poster bed with silk canopy, "
                   "sheer lace lingerie, soft butterfly lighting, "
                   "scattered silk pillows, warm gold tones, body curves accentuated by fabric, "
                   "shot on Arri Alexa Mini with 85mm f/1.4, fashion magazine quality",
        "mode": "explicit",
    },
    "gym-sweat": {
        "name": "Private Gym Workout",
        "context": "Private luxury home gym, sports bra and tight shorts, "
                   "sweat-soaked workout, muscles defined, athletic curves, "
                   "industrial lighting, mirrors reflecting body, "
                   "heavy breathing energy, post-workout flush, glistening skin texture",
        "mode": "explicit",
    },
    "rain-window": {
        "name": "Rainy Window Mood",
        "context": "Sitting nude by rain-streaked floor-to-ceiling window, city lights blurred, "
                   "moody blue-grey atmosphere, water droplet patterns on glass, "
                   "warm skin contrast against cool environment, contemplative expression, "
                   "side lighting from window, silhouette and rim light, cinematic melancholy",
        "mode": "explicit",
    },
}


@dataclass
class SubjectConfig:
    """Configuration for a generation subject."""
    name: str
    display_name: str = ""
    enabled: bool = True
    themes: list[str] = field(default_factory=lambda: list(BUILTIN_THEMES.keys()))
    images_per_drop: int = DEFAULT_IMAGES_PER_DROP
    mode: str = "explicit"  # "explicit" or "sfw"
    last_theme_index: int = 0
    last_generated: float = 0.0
    total_generated: int = 0
    priority: int = 1  # Higher = more frequent selection
    notes: str = ""

    @property
    def ref_dir(self) -> Path:
        return SUBJECTS_DIR / self.name

    @property
    def has_refs(self) -> bool:
        if not self.ref_dir.exists():
            return False
        return any(
            f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
            for f in self.ref_dir.iterdir()
        )


@dataclass
class SchedulerState:
    """Persistent scheduler state."""
    enabled: bool = True
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES
    quiet_start: int = DEFAULT_QUIET_HOURS[0]
    quiet_end: int = DEFAULT_QUIET_HOURS[1]
    total_runs: int = 0
    last_run: float = 0.0
    last_subject: str = ""
    last_theme: str = ""


class GenScheduler:
    """Creates generation drops autonomously on a schedule."""

    def __init__(self) -> None:
        self._state = SchedulerState()
        self._subjects: dict[str, SubjectConfig] = {}
        self._task: asyncio.Task | None = None
        self._running = False
        self._config_path = SUBJECTS_DIR / "subjects.json"
        self._state_path = SUBJECTS_DIR / "scheduler_state.json"

    # ─── Config management ─────────────────────────────────────────────

    def load_config(self) -> None:
        """Load subjects and state from disk."""
        # Load subjects
        if self._config_path.exists():
            try:
                data = json.loads(self._config_path.read_text())
                for name, cfg in data.get("subjects", {}).items():
                    self._subjects[name] = SubjectConfig(name=name, **cfg)
                logger.info("Loaded %d subjects from config", len(self._subjects))
            except Exception as e:
                logger.warning("Failed to load subjects config: %s", e)

        # Load state
        if self._state_path.exists():
            try:
                state_data = json.loads(self._state_path.read_text())
                self._state = SchedulerState(**state_data)
                logger.info("Loaded scheduler state (runs=%d)", self._state.total_runs)
            except Exception as e:
                logger.warning("Failed to load scheduler state: %s", e)

        # Auto-discover subjects from directories
        if SUBJECTS_DIR.exists():
            for d in SUBJECTS_DIR.iterdir():
                if d.is_dir() and d.name not in self._subjects:
                    # Check for reference images
                    refs = [
                        f for f in d.iterdir()
                        if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
                    ]
                    if refs:
                        self._subjects[d.name] = SubjectConfig(
                            name=d.name,
                            display_name=d.name.replace("-", " ").replace("_", " ").title(),
                        )
                        logger.info("Auto-discovered subject: %s (%d refs)", d.name, len(refs))

    def save_config(self) -> None:
        """Persist subjects config and state."""
        SUBJECTS_DIR.mkdir(parents=True, exist_ok=True)

        # Save subjects
        subjects_data = {
            "subjects": {
                name: {
                    k: v for k, v in asdict(cfg).items()
                    if k != "name"  # name is the key
                }
                for name, cfg in self._subjects.items()
            }
        }
        self._config_path.write_text(json.dumps(subjects_data, indent=2))

        # Save state
        self._state_path.write_text(json.dumps(asdict(self._state), indent=2))

    # ─── Subject selection ─────────────────────────────────────────────

    def _select_subject(self) -> SubjectConfig | None:
        """Select next subject using weighted random (priority-based)."""
        eligible = [
            s for s in self._subjects.values()
            if s.enabled and s.has_refs
        ]
        if not eligible:
            logger.warning("No eligible subjects with reference images")
            return None

        # Weighted selection — higher priority = more likely
        weights = [s.priority for s in eligible]
        selected = random.choices(eligible, weights=weights, k=1)[0]
        return selected

    def _select_theme(self, subject: SubjectConfig) -> tuple[str, dict]:
        """Select next theme for subject, rotating through the list."""
        available = subject.themes or list(BUILTIN_THEMES.keys())

        # Rotate to next theme
        idx = subject.last_theme_index % len(available)
        theme_key = available[idx]
        subject.last_theme_index = idx + 1

        # Get theme config
        if theme_key in BUILTIN_THEMES:
            theme = BUILTIN_THEMES[theme_key]
        else:
            # Custom theme from subject config — treat as raw context
            theme = {"name": theme_key, "context": theme_key, "mode": subject.mode}

        return theme_key, theme

    # ─── Drop creation ─────────────────────────────────────────────────

    async def create_scheduled_drop(
        self,
        subject_name: str | None = None,
        theme_key: str | None = None,
    ) -> dict[str, Any]:
        """Create a new drop folder for the auto_gen scanner to process.

        Args:
            subject_name: Specific subject (or None for auto-select).
            theme_key: Specific theme (or None for auto-select/rotate).

        Returns:
            Dict with drop details.
        """
        # Select subject
        if subject_name:
            subject = self._subjects.get(subject_name)
            if not subject:
                raise ValueError(f"Unknown subject: {subject_name}")
        else:
            subject = self._select_subject()
            if not subject:
                return {"status": "skipped", "reason": "no eligible subjects"}

        # Select theme
        if theme_key:
            if theme_key in BUILTIN_THEMES:
                theme = BUILTIN_THEMES[theme_key]
            else:
                theme = {"name": theme_key, "context": theme_key, "mode": subject.mode}
        else:
            theme_key, theme = self._select_theme(subject)

        # Generate unique drop name
        timestamp = time.strftime("%Y%m%d_%H%M")
        drop_name = f"{subject.name}_{timestamp}"

        # Create drop folder
        drop_path = DROPS_DIR / drop_name
        drop_path.mkdir(parents=True, exist_ok=True)

        # Copy reference image(s) from subject library
        refs = sorted(
            [
                f for f in subject.ref_dir.iterdir()
                if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
            ],
            key=lambda f: f.stat().st_size,
            reverse=True,  # Largest first
        )

        if not refs:
            drop_path.rmdir()
            return {"status": "error", "reason": f"No reference images for {subject.name}"}

        # Copy the best reference
        ref_dest = drop_path / f"reference{refs[0].suffix}"
        shutil.copy2(refs[0], ref_dest)

        # Write context file with theme
        mode = theme.get("mode", subject.mode)
        context_lines = [
            theme["context"],
            f"\nmode: {mode}",
            f"images: {subject.images_per_drop}",
        ]
        (drop_path / "context.txt").write_text("\n".join(context_lines))

        # Update state
        subject.last_generated = time.time()
        subject.total_generated += 1
        self._state.total_runs += 1
        self._state.last_run = time.time()
        self._state.last_subject = subject.name
        self._state.last_theme = theme_key
        self.save_config()

        logger.info(
            "Scheduler created drop: %s (subject=%s, theme=%s)",
            drop_name, subject.name, theme_key,
        )

        return {
            "status": "created",
            "drop_name": drop_name,
            "subject": subject.name,
            "theme": theme_key,
            "theme_name": theme.get("name", theme_key),
            "mode": mode,
            "images": subject.images_per_drop,
            "ref_image": ref_dest.name,
        }

    # ─── Background scheduling loop ───────────────────────────────────

    def _in_quiet_hours(self) -> bool:
        """Check if current time is in quiet hours (no generation)."""
        hour = time.localtime().tm_hour
        start, end = self._state.quiet_start, self._state.quiet_end
        if start <= end:
            return start <= hour < end
        else:
            # Wraps around midnight (e.g., 23-6)
            return hour >= start or hour < end

    async def _scheduler_loop(self) -> None:
        """Background loop that creates drops on schedule."""
        logger.info(
            "Scheduler started: interval=%dm, quiet=%d:00-%d:00",
            self._state.interval_minutes,
            self._state.quiet_start,
            self._state.quiet_end,
        )

        while self._running:
            try:
                # Check if enabled
                if not self._state.enabled:
                    await asyncio.sleep(60)
                    continue

                # Check quiet hours
                if self._in_quiet_hours():
                    logger.debug("Scheduler in quiet hours, sleeping")
                    await asyncio.sleep(300)  # Check again in 5 min
                    continue

                # Check if enough time has passed since last run
                elapsed = time.time() - self._state.last_run
                interval_sec = self._state.interval_minutes * 60
                if elapsed < interval_sec:
                    remaining = interval_sec - elapsed
                    await asyncio.sleep(min(remaining, 60))
                    continue

                # Time to generate!
                result = await self.create_scheduled_drop()
                logger.info("Scheduled generation: %s", result)

                # Sleep for the full interval
                await asyncio.sleep(self._state.interval_minutes * 60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Scheduler error: %s", e)
                await asyncio.sleep(60)

        logger.info("Scheduler stopped")

    def start(self, interval_minutes: int | None = None) -> None:
        """Start the background scheduler."""
        if self._task and not self._task.done():
            logger.warning("Scheduler already running")
            return

        self.load_config()

        if interval_minutes is not None:
            self._state.interval_minutes = interval_minutes
            self.save_config()

        self._running = True
        self._task = asyncio.get_event_loop().create_task(self._scheduler_loop())
        logger.info("Scheduler started with %d subjects", len(self._subjects))

    def stop(self) -> None:
        """Stop the background scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        self.save_config()
        logger.info("Scheduler stopped, state saved")

    # ─── Status & management ──────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Get scheduler status for API."""
        subjects_info = []
        for s in self._subjects.values():
            info = {
                "name": s.name,
                "display_name": s.display_name or s.name,
                "enabled": s.enabled,
                "has_refs": s.has_refs,
                "themes": len(s.themes) if s.themes else len(BUILTIN_THEMES),
                "total_generated": s.total_generated,
                "priority": s.priority,
                "mode": s.mode,
            }
            if s.last_generated:
                info["last_generated"] = time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(s.last_generated)
                )
            subjects_info.append(info)

        # Time until next run
        next_run_in = None
        if self._state.enabled and self._state.last_run:
            remaining = (self._state.interval_minutes * 60) - (time.time() - self._state.last_run)
            if remaining > 0:
                next_run_in = int(remaining)

        return {
            "running": self._running,
            "enabled": self._state.enabled,
            "interval_minutes": self._state.interval_minutes,
            "quiet_hours": f"{self._state.quiet_start:02d}:00-{self._state.quiet_end:02d}:00",
            "total_runs": self._state.total_runs,
            "next_run_in_seconds": next_run_in,
            "last_run": time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(self._state.last_run)
            ) if self._state.last_run else None,
            "last_subject": self._state.last_subject,
            "last_theme": self._state.last_theme,
            "subjects": subjects_info,
            "available_themes": list(BUILTIN_THEMES.keys()),
        }

    def add_subject(
        self,
        name: str,
        display_name: str = "",
        themes: list[str] | None = None,
        mode: str = "explicit",
        priority: int = 1,
    ) -> SubjectConfig:
        """Register a new subject (reference images must be added to the folder)."""
        subject = SubjectConfig(
            name=name,
            display_name=display_name or name.replace("-", " ").replace("_", " ").title(),
            themes=themes or list(BUILTIN_THEMES.keys()),
            mode=mode,
            priority=priority,
        )
        subject.ref_dir.mkdir(parents=True, exist_ok=True)
        self._subjects[name] = subject
        self.save_config()
        return subject

    def remove_subject(self, name: str) -> bool:
        """Remove a subject (does not delete files)."""
        if name in self._subjects:
            del self._subjects[name]
            self.save_config()
            return True
        return False


# Module-level singleton
gen_scheduler = GenScheduler()
