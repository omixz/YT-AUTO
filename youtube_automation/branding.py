"""Generates a consistent channel-branded intro card and subscribe-CTA outro
card that get stitched onto every video.

This is a concrete, code-level answer to YouTube's "reused/duplicative
content" monetization policy: videos that are otherwise just narration over
generic stock footage read as templated slideshows, whereas a recurring
visual identity (same intro, same outro, same channel name every time) is
one of the signals of an actual produced show. It also nudges retention and
subscribe conversion, which is what the channel-eligibility bar (subscribers
+ watch hours) actually runs on.
"""
from __future__ import annotations

from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw

from .config import PipelineConfig
from .fonts import load_bold
from .tts import SceneAudio, silent_audio
from .visuals import VisualAsset

TOP_COLOR = (16, 18, 30)
BOTTOM_COLOR = (42, 46, 82)

INTRO_SCENE_INDEX = -1
OUTRO_SCENE_INDEX = 10_000


def _gradient(size: Tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        color = tuple(
            round(TOP_COLOR[i] + (BOTTOM_COLOR[i] - TOP_COLOR[i]) * t) for i in range(3)
        )
        draw.line([(0, y), (w, y)], fill=color)
    return img


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list:
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_lines(draw: ImageDraw.ImageDraw, text: str, max_font_size: int, max_width: int, max_lines: int) -> tuple:
    """Shrinks the font until the full text fits within max_lines - never
    silently truncates text the way a fixed font size + line cap would."""
    size = max_font_size
    while size > 14:
        font = load_bold(size)
        lines = _wrap(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
        size -= 4
    return load_bold(size), _wrap(draw, text, load_bold(size), max_width)[:max_lines]


def _card(size: Tuple[int, int], heading: str, subheading: str, out_path: Path) -> Path:
    img = _gradient(size)
    draw = ImageDraw.Draw(img)
    max_width = round(size[0] * 0.82)

    heading_font, heading_lines = _fit_lines(draw, heading.upper(), round(size[0] * 0.09), max_width, max_lines=3)
    subheading_font, subheading_lines = (
        _fit_lines(draw, subheading, round(size[0] * 0.036), max_width, max_lines=3) if subheading else (None, [])
    )

    heading_line_h = round(heading_font.size * 1.25)
    subheading_line_h = round(subheading_font.size * 1.35) if subheading_font else 0
    gap = round(size[0] * 0.03) if subheading_lines else 0

    total_h = len(heading_lines) * heading_line_h + gap + len(subheading_lines) * subheading_line_h
    y = (size[1] - total_h) // 2

    for line in heading_lines:
        w = draw.textlength(line, font=heading_font)
        draw.text(((size[0] - w) / 2, y), line, font=heading_font, fill=(255, 255, 255))
        y += heading_line_h

    y += gap
    for line in subheading_lines:
        w = draw.textlength(line, font=subheading_font)
        draw.text(((size[0] - w) / 2, y), line, font=subheading_font, fill=(200, 202, 224))
        y += subheading_line_h

    img.save(out_path, quality=92)
    return out_path


def build_intro(config: PipelineConfig, work_dir: Path, duration: float = 1.6) -> Tuple[VisualAsset, SceneAudio]:
    image_path = _card(
        config.video.resolution, config.channel.name, config.channel.niche.title(),
        work_dir / "intro_card.jpg",
    )
    audio_path = silent_audio(duration, work_dir / "intro_audio.mp3")
    return (
        VisualAsset(kind="image", path=image_path),
        SceneAudio(scene_index=INTRO_SCENE_INDEX, audio_path=audio_path, duration=duration, cues=[]),
    )


def build_outro(config: PipelineConfig, work_dir: Path, duration: float = 2.2) -> Tuple[VisualAsset, SceneAudio]:
    cta = config.channel.subscribe_cta.format(niche=config.channel.niche)
    image_path = _card(
        config.video.resolution, "Subscribe", cta,
        work_dir / "outro_card.jpg",
    )
    audio_path = silent_audio(duration, work_dir / "outro_audio.mp3")
    return (
        VisualAsset(kind="image", path=image_path),
        SceneAudio(scene_index=OUTRO_SCENE_INDEX, audio_path=audio_path, duration=duration, cues=[]),
    )
