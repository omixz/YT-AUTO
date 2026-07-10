"""Shared bold-font lookup for thumbnail.py and branding.py."""
from __future__ import annotations

from pathlib import Path

from PIL import ImageFont

CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def load_bold(size: int) -> ImageFont.ImageFont:
    for path in CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()
