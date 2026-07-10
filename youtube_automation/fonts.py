"""Shared font lookup for thumbnail.py, branding.py, and animation.py.

Outfit (bundled under assets/fonts/, SIL Open Font License - see
assets/fonts/LICENSE.txt) is a modern geometric sans used everywhere text is
rendered, so it's tried first regardless of what fonts happen to be
installed on the machine running this. The system fonts are a fallback only
for environments where the repo's assets/ somehow isn't on disk.
"""
from __future__ import annotations

from pathlib import Path

from PIL import ImageFont

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

BOLD_CANDIDATES = [
    ASSETS_DIR / "Outfit-Bold.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
]

REGULAR_CANDIDATES = [
    ASSETS_DIR / "Outfit-Regular.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
]


def load_bold(size: int) -> ImageFont.ImageFont:
    for path in BOLD_CANDIDATES:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def load_regular(size: int) -> ImageFont.ImageFont:
    for path in REGULAR_CANDIDATES:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()
