"""Generates one crude, hand-drawn-doodle illustration per scene via
Pollinations.ai's free, keyless image API (https://pollinations.ai) - no
billing, no API key. Each image depicts that scene's specific narration
content directly (the figure IS the subject of the scene - a Hitler Youth
topic gets a child in that uniform, not a generic floating mascot), which
is why this reads scene.narration directly rather than the more abstract
visual_keywords used for stock-footage search / SFX matching elsewhere.
"""
from __future__ import annotations

import logging
import time
import urllib.parse
from pathlib import Path
from typing import List

import requests

from .config import PipelineConfig
from .script_writer import Scene

logger = logging.getLogger(__name__)

BASE_URL = "https://image.pollinations.ai/prompt/"
_MAX_RETRIES = 4
_RETRY_BACKOFF = 2.0

# The user's exact "MASTER IMAGE PROMPT" style spec, plus their follow-up
# refinement (minimal expression-only faces, everyone bald or head-covered)
# - image models default toward polished, good-looking output even when
# asked for something crude, so this stays close to their literal wording
# rather than a paraphrase.
STYLE_SUFFIX = (
    "STYLE (follow exactly): Looks like an extremely simple, rushed beginner drawing made in MS Paint. "
    "Like someone who is NOT good at drawing made it quickly by hand. Plain flat background (a simple "
    "white/light sky, no photorealistic or gradient backdrop), but DO draw the actual setting as simple "
    "flat shapes in the same crude style (buildings, snow, mountains, streets, rooms, vehicles, whatever "
    "the scene is set in) - the environment matters as much as any character in it. "
    "No 3D, no cinematic lighting, no realistic detail, no fancy rendering. "
    "Crude, flat, hand-drawn, slightly messy on purpose. "
    "Flat 2D vector clip-art style, like a simple flat-icon illustration or a Duolingo-style mascot - "
    "every clothing item and object is a single solid flat color with a thick black outline, absolutely "
    "no shading, no gradients, no highlights, no folds, no texture, no cel-shading, no painterly rendering "
    "anywhere in the image. "
    "If a character appears, they're a normal-sized small part of a wider scene, not a large close-up "
    "portrait filling the frame - the setting should be clearly visible around them. "
    "Any faces are extremely minimal - just a plain circle or oval head with a single simple curved line "
    "for a mouth showing the expression (a smile, a frown, an upside-down smile, or a flat straight line) - "
    "no detailed eyes, no nose, no eyebrows, no realistic facial features at all, just two small dots for "
    "eyes. Every character is bald or has something covering their head (a helmet, hat, cap, hood, crown, "
    "or similar) - never draw hair."
)


def _prompt_for_scene(scene: Scene) -> str:
    return f"Wide shot of this scene, showing the full setting: {scene.narration.strip()}. {STYLE_SUFFIX}"


def generate_scene_image(scene: Scene, index: int, config: PipelineConfig, work_dir: Path) -> Path:
    prompt = _prompt_for_scene(scene)
    w, h = config.video.resolution
    url = BASE_URL + urllib.parse.quote(prompt)
    params = {"width": w, "height": h, "nologo": "true", "seed": index, "model": "flux"}

    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=90)
            resp.raise_for_status()
            if resp.headers.get("content-type", "").startswith("image/") and len(resp.content) > 1000:
                path = work_dir / f"scene_{index:02d}_illustration.jpg"
                path.write_bytes(resp.content)
                return path
            last_exc = RuntimeError(f"unexpected response ({resp.headers.get('content-type')}, {len(resp.content)} bytes)")
        except requests.RequestException as exc:
            last_exc = exc

        if attempt < _MAX_RETRIES - 1:
            logger.warning("Illustration generation failed for scene %d (attempt %d/%d): %s", index, attempt + 1, _MAX_RETRIES, last_exc)
            time.sleep(_RETRY_BACKOFF ** attempt)

    raise RuntimeError(f"Failed to generate illustration for scene {index} after {_MAX_RETRIES} attempts: {last_exc}")


def generate_all(scenes: List[Scene], config: PipelineConfig, work_dir: Path) -> List[Path]:
    return [generate_scene_image(scene, i, config, work_dir) for i, scene in enumerate(scenes)]
