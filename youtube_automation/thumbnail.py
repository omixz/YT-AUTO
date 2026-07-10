"""Generates a 1280x720 YouTube thumbnail from a scene frame + bold title text.

YouTube's thumbnails.set endpoint expects a standard 16:9 image regardless of
whether the video itself is portrait (Shorts) or landscape.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .visuals import VisualAsset

THUMB_SIZE = (1280, 720)
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _load_font(size: int) -> ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _extract_frame(asset: VisualAsset, out_path: Path) -> Path:
    if asset.kind == "image":
        return asset.path
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(asset.path), "-ss", "00:00:00.5", "-frames:v", "1", str(out_path)],
        check=True, capture_output=True,
    )
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


def _wrap_title(draw: ImageDraw.ImageDraw, title: str, font: ImageFont.ImageFont, max_width: int) -> list:
    words = title.upper().split()
    lines = []
    current = ""
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
    return lines[:3]


def generate(title: str, background_asset: VisualAsset, work_dir: Path, out_path: Path) -> Path:
    frame_path = _extract_frame(background_asset, work_dir / "thumb_source.jpg")

    bg = Image.open(frame_path).convert("RGB")
    bg = _cover_resize(bg, THUMB_SIZE).convert("RGBA")

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
    font = _load_font(font_size)
    margin = 60
    max_width = THUMB_SIZE[0] - 2 * margin

    lines = _wrap_title(draw, title, font, max_width)
    line_height = font_size + 14
    y = THUMB_SIZE[1] - margin - line_height * len(lines)

    for line in lines:
        draw.text(
            (margin, y), line, font=font, fill=(255, 255, 255, 255),
            stroke_width=4, stroke_fill=(0, 0, 0, 255),
        )
        y += line_height

    bg.convert("RGB").save(out_path, quality=92)
    return out_path
