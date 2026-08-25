"""Generates a 1280x720 YouTube thumbnail from a scene frame + bold title text.

YouTube's thumbnails.set endpoint expects a standard 16:9 image regardless of
whether the video itself is portrait (Shorts) or landscape.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from .fonts import load_bold
from .visuals import VisualAsset

THUMB_SIZE = (1280, 720)

# A bright, high-contrast accent distinct from the white body text - the
# classic "one word in a different color" thumbnail trick to draw the eye
# in a crowded feed. Deliberately not config.animation.accent_color (that
# defaults to white, which wouldn't read as a highlight against white text).
HIGHLIGHT_COLOR = (255, 209, 0)

# Words that make a title's specific curiosity-gap payoff legible at a
# glance - if the title contains one, highlighting it (rather than an
# arbitrary word) is what actually earns the click. Deliberately not used
# to gate/reject titles (see quality_check.py's docstring on why an
# allow-list of "hook phrases" was a bad idea) - this only picks which
# word gets colored differently, a good title with none of these still
# renders fine via the numeral/last-word fallbacks below.
_POWER_WORDS = {
    "secret", "secrets", "hidden", "banned", "forbidden", "cursed", "vanished",
    "disappeared", "died", "death", "killed", "murder", "murdered", "destroyed",
    "collapse", "collapsed", "shocking", "terrifying", "true", "real", "actually",
    "never", "lost", "betrayed", "betrayal", "escape", "trapped", "doomed",
    "warning", "danger", "mystery", "unsolved", "revealed", "truth", "why",
}


def _pick_highlight_word(title_words: List[str]) -> Optional[str]:
    for word in title_words:
        if word.strip(".,!?:;\"'’").lower() in _POWER_WORDS:
            return word
    for word in title_words:
        if any(ch.isdigit() for ch in word):
            return word
    return title_words[-1] if title_words else None


def _extract_frame(asset: VisualAsset, out_path: Path) -> Path:
    if asset.kind == "image":
        return asset.path

    if asset.kind == "prerendered":
        # animation.py's own kinetic on-screen text fades in over the first
        # 25% of a scene, so grabbing any later frame risks catching it
        # half-visible and colliding with the thumbnail's own title text
        # below. At frame 0 its alpha is exactly 0 - always clean, and
        # (unlike real stock footage) there's no black-intro-frame risk
        # since these are programmatically generated.
        cmd = ["ffmpeg", "-y", "-i", str(asset.path), "-frames:v", "1", str(out_path)]
    else:
        # Real stock video: skip past a possible black/fade-in intro frame.
        # If the clip is shorter than 0.5s, fall back to frame 0 rather than
        # letting ffmpeg fail with an empty output.
        cmd = ["ffmpeg", "-y", "-i", str(asset.path), "-ss", "00:00:00.5", "-frames:v", "1", str(out_path)]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            cmd = ["ffmpeg", "-y", "-i", str(asset.path), "-frames:v", "1", str(out_path)]

    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def _cover_resize(img: Image.Image, size: tuple) -> Image.Image:
    target_w, target_h = size
    src_ratio = img.width / img.height
    target_ratio = target_w / target_h
    if src_ratio > target_ratio:
        new_h = target_h
        new_w = round(new_h * src_ratio)
    else:
        new_w = target_w
        new_h = round(new_w / src_ratio)
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def _wrap_title(draw: ImageDraw.ImageDraw, words: List[str], font: ImageFont.ImageFont, max_width: int) -> List[List[str]]:
    """Wraps into lines of words (not joined strings) so the caller can
    render - and color - each word individually, for the highlight-word
    treatment in generate()."""
    lines: List[List[str]] = []
    current: List[str] = []
    for word in words:
        candidate = " ".join(current + [word])
        if draw.textlength(candidate, font=font) <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(current)
            current = [word]
    if current:
        lines.append(current)
    return lines[:3]


def generate(title: str, background_asset: VisualAsset, work_dir: Path, out_path: Path) -> Path:
    frame_path = _extract_frame(background_asset, work_dir / "thumb_source.jpg")

    bg = Image.open(frame_path).convert("RGB")
    bg = _cover_resize(bg, THUMB_SIZE)

    # Punchier colors read better at thumbnail size in a crowded, scrollable
    # feed than the source frame's natural contrast/saturation - a flat
    # boost here is the same trick most high-CTR thumbnails use.
    bg = ImageEnhance.Color(bg).enhance(1.35)
    bg = ImageEnhance.Contrast(bg).enhance(1.12)
    bg = bg.convert("RGBA")

    # Dark gradient at the bottom so white title text stays legible over any photo.
    overlay = Image.new("RGBA", THUMB_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    gradient_top = THUMB_SIZE[1] - 320
    for y in range(gradient_top, THUMB_SIZE[1]):
        alpha = int(190 * (y - gradient_top) / (THUMB_SIZE[1] - gradient_top))
        draw.line([(0, y), (THUMB_SIZE[0], y)], fill=(0, 0, 0, alpha))
    bg = Image.alpha_composite(bg, overlay)

    draw = ImageDraw.Draw(bg)
    font_size = 76
    font = load_bold(font_size)
    margin = 60
    max_width = THUMB_SIZE[0] - 2 * margin

    words = title.upper().split()
    highlight = _pick_highlight_word(words)
    lines = _wrap_title(draw, words, font, max_width)
    line_height = font_size + 14
    y = THUMB_SIZE[1] - margin - line_height * len(lines)
    space_width = draw.textlength(" ", font=font)

    for line_words in lines:
        x = margin
        for word in line_words:
            color = HIGHLIGHT_COLOR if word == highlight else (255, 255, 255)
            draw.text(
                (x, y), word, font=font, fill=color,
                stroke_width=4, stroke_fill=(0, 0, 0, 255),
            )
            x += draw.textlength(word, font=font) + space_width
        y += line_height

    bg.convert("RGB").save(out_path, quality=92)
    return out_path
