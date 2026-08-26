"""Generates YouTube thumbnails (1280x720) with multiple composition strategies
and an A/B test framework. Each call produces 3 variants by default:
- VARIANT_A: Rule-of-thirds, text on right third, focal subject on left
- VARIANT_B: Centered bold title, vignette background, color-graded
- VARIANT_C: Split layout (text left, image right) with accent bar

All variants share the same source frame but differ in composition, text
treatment, and color grading - enabling real CTR A/B testing via
YouTube's thumbnail rotation or manual swaps.
"""
from __future__ import annotations

import colorsys
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .fonts import load_bold
from .visuals import VisualAsset

THUMB_SIZE = (1280, 720)
THUMB_W, THUMB_H = THUMB_SIZE

# Backwards-compat constant used by tests
HIGHLIGHT_COLOR = (255, 209, 0)

# --- Color palettes per emotional tone (HSV -> RGB) -------------------------
# Each palette: (primary_text_HSV, highlight_HSV, overlay_tint_RGBA, bg_tint_RGB)
# HSV: Hue(0-360), Saturation(0-100), Value(0-100)
# Highlight colors are chosen for maximum contrast at thumbnail size.
_PALETTES = {
    "dramatic":     ((0, 0, 100), (47, 100, 100), (0, 0, 0, 180), (30, 60, 60)),
    "curious":      ((0, 0, 100), (210, 90, 100), (220, 40, 15, 160), (230, 25, 20)),
    "shocking":     ((0, 0, 100), (0, 100, 100), (0, 0, 0, 200), (10, 80, 30)),
    "educational":  ((0, 0, 100), (60, 80, 100), (200, 50, 10, 150), (210, 30, 25)),
    "story":        ((0, 0, 100), (30, 70, 100), (40, 30, 10, 170), (50, 25, 20)),
    "default":      ((0, 0, 100), (47, 100, 100), (0, 0, 0, 180), (30, 60, 60)),
}

# Power words that get highlight color when present in title
_POWER_WORDS = {
    "secret", "secrets", "hidden", "banned", "forbidden", "cursed", "vanished",
    "disappeared", "died", "death", "killed", "murder", "murdered", "destroyed",
    "collapse", "collapsed", "shocking", "terrifying", "true", "real", "actually",
    "never", "lost", "betrayed", "betrayal", "escape", "trapped", "doomed",
    "warning", "danger", "mystery", "unsolved", "revealed", "truth", "why",
}

# Third-grid intersection points (x, y) for rule-of-thirds placement
_THIRDS = [
    (THUMB_W // 3, THUMB_H // 3),          # top-left
    (2 * THUMB_W // 3, THUMB_H // 3),      # top-right
    (THUMB_W // 3, 2 * THUMB_H // 3),      # bottom-left
    (2 * THUMB_W // 3, 2 * THUMB_H // 3),  # bottom-right
]


@dataclass
class ThumbnailVariant:
    path: Path
    name: str
    composition: str  # "rule_of_thirds", "centered", "split"


def _hsv_to_rgb(h: float, s: float, v: float) -> Tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(h / 360, s / 100, v / 100)
    return (int(r * 255), int(g * 255), int(b * 255))


def _pick_palette(tone: str) -> Tuple[Tuple[int, int, int], Tuple[int, int, int], Tuple[int, int, int, int], Tuple[int, int, int]]:
    p = _PALETTES.get(tone.lower(), _PALETTES["default"])
    return (
        _hsv_to_rgb(*p[0]),           # primary text (white)
        _hsv_to_rgb(*p[1]),           # highlight accent
        p[2],                          # overlay tint (RGBA)
        _hsv_to_rgb(*p[3]),           # background tint (RGB)
    )


def _pick_highlight_word(words: List[str]) -> Optional[str]:
    for w in words:
        if w.strip(".,!?:;\"'").lower() in _POWER_WORDS:
            return w
    for w in words:
        if any(c.isdigit() for c in w):
            return w
    return words[-1] if words else None


def _extract_frame(asset: VisualAsset, out_path: Path) -> Path:
    if asset.kind == "image":
        return asset.path

    if asset.kind == "prerendered":
        cmd = ["ffmpeg", "-y", "-i", str(asset.path), "-frames:v", "1", str(out_path)]
    else:
        cmd = ["ffmpeg", "-y", "-i", str(asset.path), "-ss", "00:00:00.5", "-frames:v", "1", str(out_path)]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            cmd = ["ffmpeg", "-y", "-i", str(asset.path), "-frames:v", "1", str(out_path)]

    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def _cover_resize(img: Image.Image, size: Tuple[int, int]) -> Image.Image:
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


def _apply_color_grading(img: Image.Image, tint_rgb: Tuple[int, int, int], strength: float = 0.15) -> Image.Image:
    """Subtle color grade toward a tint (like cinematic LUTs)."""
    overlay = Image.new("RGB", img.size, tint_rgb)
    return Image.blend(img, overlay, strength)


def _vignette(img: Image.Image, intensity: float = 0.35) -> Image.Image:
    """Darken the far corners to pull the eye toward center - the center
    itself should end up essentially untouched (mask alpha ~0 there) and
    only the corners approach `intensity`.

    This used to build the mask by drawing ~360 concentric 1px-wide ellipse
    OUTLINES with alpha DECREASING inward from a 255 (fully opaque) base -
    which both starts every pixel at max darkness and only ever dips to
    ~255*(1-intensity) at the exact center, instead of tapering to 0 there.
    Measured directly: center-pixel alpha came out to 192/255 (~75% opacity
    black) instead of ~0 - every thumbnail rendered almost entirely black
    regardless of intensity, not just the corners. Rewritten as an actual
    radial gradient from the center outward."""
    w, h = img.size
    cx, cy = w / 2, h / 2
    max_dist = math.hypot(cx, cy)
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.hypot(xx - cx, yy - cy) / max_dist  # 0 at center, 1 at the corners
    alpha = (np.clip(dist, 0, 1) ** 2) * intensity * 255
    mask = Image.fromarray(alpha.astype(np.uint8), mode="L")
    mask = mask.filter(ImageFilter.GaussianBlur(radius=40))
    dark = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dark.putalpha(mask)
    return Image.alpha_composite(img.convert("RGBA"), dark).convert("RGB")


def _gradient_overlay(img: Image.Image, color: Tuple[int, int, int, int], direction: str = "bottom") -> Image.Image:
    """Add a gradient overlay (for text legibility)."""
    w, h = img.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    if direction == "bottom":
        start_y = h - 280
        for y in range(start_y, h):
            alpha = int(color[3] * ((y - start_y) / (h - start_y)) ** 1.5)
            draw.line([(0, y), (w, y)], fill=(color[0], color[1], color[2], alpha))
    elif direction == "left":
        end_x = w // 2
        for x in range(end_x):
            alpha = int(color[3] * (1 - x / end_x) ** 1.2)
            draw.line([(x, 0), (x, h)], fill=(color[0], color[1], color[2], alpha))
    return Image.alpha_composite(img.convert("RGBA"), overlay)


def _wrap_lines(draw: ImageDraw.ImageDraw, words: List[str], font: ImageFont.ImageFont, max_width: int, max_lines: int = 3) -> List[List[str]]:
    """Wrap words into lines, return list of word-lists (not joined) for per-word coloring."""
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
    return lines[:max_lines]


def _draw_text_with_effects(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    word: str,
    font: ImageFont.ImageFont,
    color: Tuple[int, int, int],
    highlight_color: Tuple[int, int, int],
    highlight_word: Optional[str],
    stroke_width: int = 4,
) -> int:
    """Draw a single word with stroke + drop shadow. Returns advance width."""
    is_highlight = (word == highlight_word)
    fill = highlight_color if is_highlight else color

    # Drop shadow (offset 3,3)
    draw.text((x + 3, y + 3), word, font=font, fill=(0, 0, 0, 180), stroke_width=0)
    # Main text with stroke
    draw.text((x, y), word, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=(0, 0, 0, 255))
    return draw.textlength(word, font=font) + draw.textlength(" ", font=font)


def _render_variant_a(img: Image.Image, title: str, tone: str, work_dir: Path, variant_id: str) -> Path:
    """VARIANT_A: Rule-of-thirds. Text on right third, image enhanced."""
    w, h = THUMB_SIZE
    bg = img.copy()

    # Color grade toward palette
    _, _, _, tint_rgb = _pick_palette(tone)
    bg = _apply_color_grading(bg, tint_rgb, strength=0.18)
    bg = ImageEnhance.Color(bg).enhance(1.4)
    bg = ImageEnhance.Contrast(bg).enhance(1.15)
    bg = _vignette(bg, intensity=0.3)

    primary, highlight, overlay_rgba, _ = _pick_palette(tone)
    bg = _gradient_overlay(bg.convert("RGBA"), overlay_rgba, direction="bottom").convert("RGB")

    draw = ImageDraw.Draw(bg)
    words = title.upper().split()
    highlight_word = _pick_highlight_word(words)

    # Dynamic font sizing: start big, shrink to fit 3 lines
    font_size = 84
    margin = 70
    max_width = w - 2 * margin
    font = load_bold(font_size)
    lines = _wrap_lines(draw, words, font, max_width)
    while len(lines) > 3 and font_size > 48:
        font_size -= 4
        font = load_bold(font_size)
        lines = _wrap_lines(draw, words, font, max_width)

    line_height = font_size + 16
    # Place text on RIGHT third (bottom-right intersection)
    y = _THIRDS[3][1] - (line_height * len(lines)) // 2
    for line_words in lines:
        line_w = sum(draw.textlength(w, font=font) + draw.textlength(" ", font=font) for w in line_words)
        x = w - margin - line_w  # right-aligned
        for word in line_words:
            x += _draw_text_with_effects(draw, x, y, word, font, primary, highlight, highlight_word)
        y += line_height

    out = work_dir / f"thumb_{variant_id}_A.jpg"
    bg.save(out, quality=95, optimize=True)
    return out


def _render_variant_b(img: Image.Image, title: str, tone: str, work_dir: Path, variant_id: str) -> Path:
    """VARIANT_B: Centered bold. Strong vignette, high contrast, text centered."""
    w, h = THUMB_SIZE
    bg = img.copy()

    _, _, _, tint_rgb = _pick_palette(tone)
    bg = _apply_color_grading(bg, tint_rgb, strength=0.22)
    bg = ImageEnhance.Color(bg).enhance(1.5)
    bg = ImageEnhance.Contrast(bg).enhance(1.25)
    bg = _vignette(bg, intensity=0.45)

    primary, highlight, overlay_rgba, _ = _pick_palette(tone)
    bg = _gradient_overlay(bg.convert("RGBA"), overlay_rgba, direction="bottom").convert("RGB")

    draw = ImageDraw.Draw(bg)
    words = title.upper().split()
    highlight_word = _pick_highlight_word(words)

    font_size = 92
    margin = 80
    max_width = w - 2 * margin
    font = load_bold(font_size)
    lines = _wrap_lines(draw, words, font, max_width)
    while len(lines) > 3 and font_size > 52:
        font_size -= 4
        font = load_bold(font_size)
        lines = _wrap_lines(draw, words, font, max_width)

    line_height = font_size + 18
    y = h // 2 - (line_height * len(lines)) // 2
    for line_words in lines:
        line_w = sum(draw.textlength(w, font=font) + draw.textlength(" ", font=font) for w in line_words)
        x = (w - line_w) // 2
        for word in line_words:
            x += _draw_text_with_effects(draw, x, y, word, font, primary, highlight, highlight_word, stroke_width=5)
        y += line_height

    out = work_dir / f"thumb_{variant_id}_B.jpg"
    bg.save(out, quality=95, optimize=True)
    return out


def _render_variant_c(img: Image.Image, title: str, tone: str, work_dir: Path, variant_id: str) -> Path:
    """VARIANT_C: Split layout. Accent bar on left, text left, image right."""
    w, h = THUMB_SIZE
    bg = img.copy()

    _, highlight, _, _ = _pick_palette(tone)
    bg = ImageEnhance.Color(bg).enhance(1.3)
    bg = ImageEnhance.Contrast(bg).enhance(1.1)
    bg = _vignette(bg, intensity=0.25)

    # Left accent bar (gold/color stripe)
    bar_w = 18
    draw = ImageDraw.Draw(bg)
    draw.rectangle([0, 0, bar_w, h], fill=highlight)

    primary, _, overlay_rgba, _ = _pick_palette(tone)
    bg = _gradient_overlay(bg.convert("RGBA"), overlay_rgba, direction="left").convert("RGB")
    draw = ImageDraw.Draw(bg)

    words = title.upper().split()
    highlight_word = _pick_highlight_word(words)

    font_size = 78
    margin = 60
    max_width = w // 2 - 2 * margin  # left half
    font = load_bold(font_size)
    lines = _wrap_lines(draw, words, font, max_width)
    while len(lines) > 4 and font_size > 44:
        font_size -= 4
        font = load_bold(font_size)
        lines = _wrap_lines(draw, words, font, max_width)

    line_height = font_size + 14
    y = h // 2 - (line_height * len(lines)) // 2
    x_start = bar_w + margin
    for line_words in lines:
        x = x_start
        for word in line_words:
            x += _draw_text_with_effects(draw, x, y, word, font, primary, highlight, highlight_word)
        y += line_height

    out = work_dir / f"thumb_{variant_id}_C.jpg"
    bg.save(out, quality=95, optimize=True)
    return out


def generate_variants(
    title: str,
    background_asset: VisualAsset,
    work_dir: Path,
    tone: str = "dramatic",
    variant_id: str = "v1",
) -> List[ThumbnailVariant]:
    """Generate 3 A/B test variants from the same source frame."""
    work_dir = Path(work_dir) if not isinstance(work_dir, Path) else work_dir
    frame_path = _extract_frame(background_asset, work_dir / f"thumb_source_{variant_id}.jpg")
    base = Image.open(frame_path).convert("RGB")
    base = _cover_resize(base, THUMB_SIZE)

    return [
        ThumbnailVariant(_render_variant_a(base, title, tone, work_dir, variant_id), f"{variant_id}_A", "rule_of_thirds"),
        ThumbnailVariant(_render_variant_b(base, title, tone, work_dir, variant_id), f"{variant_id}_B", "centered"),
        ThumbnailVariant(_render_variant_c(base, title, tone, work_dir, variant_id), f"{variant_id}_C", "split"),
    ]


def generate(
    title: str,
    background_asset: VisualAsset,
    work_dir: Path,
    out_path: Path,
    tone: str = "dramatic",
) -> Path:
    """Backwards-compatible single-thumbnail generation (returns VARIANT_A)."""
    variants = generate_variants(title, background_asset, work_dir, tone=tone, variant_id="main")
    # Copy the first variant to the requested out_path
    import shutil
    shutil.copy2(variants[0].path, out_path)
    return out_path