"""Cartoon thumbnails built for click-through: ONE big expressive face, a sunburst behind it,
a huge 2-3 word caption, high contrast. Replaces 'best frame + the whole title in small type',
which was text-heavy and just repeated the title."""
from __future__ import annotations

import math
import random
import re
import zlib
from pathlib import Path
from typing import List, Optional

import skia

from ..fonts import ASSETS_DIR
from . import character as C
from . import direction, fx
from .art import INK, col, fill, stroke
from .sets import build_set

W, H = 1280, 720
_STOP = {"the", "a", "an", "of", "in", "on", "at", "to", "and", "that", "this", "how", "why", "what", "who", "where", "when", "with", "for", "was", "were", "is"}
_PUNCH = ("vanish", "disappear", "murder", "secret", "lost", "last", "never", "dead", "death", "mystery", "hidden", "forbidden",
          "cursed", "final", "impossible", "terrif", "strange", "betray", "trap", "doomed", "survivor", "unsolved", "massacre", "plague", "curse")
_CERTAIN = re.compile(r"\b(proves?|proof|proven|confirmed|exposed|the (real|hidden|shocking) truth)\b", re.I)


def pick_text(title: str, provided: str = "") -> str:
    """Thumbnail words: the model's `thumbnail_text` if it is short and honest, else a heuristic cut of the title."""
    p = (provided or "").strip().strip('"')
    if p and 1 <= len(p.split()) <= 4 and len(p) <= 28 and not _CERTAIN.search(p):
        return p.upper()
    parts = [x.strip() for x in re.split(r"[:\u2014\u2013|]| - ", title) if x.strip()]
    for part in reversed(parts):                       # prefer a short clause after the colon
        w = part.split()
        if 1 <= len(w) <= 4 and not _CERTAIN.search(part):
            return part.upper()
    words = [w.strip("\"'.,!?") for w in title.split()]
    punchy = [w for w in words if any(k in w.lower() for k in _PUNCH)]
    keep = (punchy[:2] + [w for w in words if w.lower() not in _STOP and w not in punchy])[:3]
    return " ".join(keep).upper() or title.upper()[:20]


def _typeface():
    path = ASSETS_DIR / "Outfit-Bold.ttf"
    tf = skia.Typeface.MakeFromFile(str(path)) if path.exists() else None
    return tf or skia.Typeface("DejaVu Sans", skia.FontStyle.Bold())


def _draw_caption(canvas, text: str, x0: float, x1: float, mood: str) -> None:
    words = text.split()
    lines = words if len(words) <= 3 else [" ".join(words[:2]), " ".join(words[2:])]
    tf = _typeface()
    size = 190.0
    while size > 60:
        font = skia.Font(tf, size)
        if max(font.measureText(l) for l in lines) <= (x1 - x0):
            break
        size -= 6
    font = skia.Font(tf, size)
    hl = (255, 214, 64) if mood != "serious" else (255, 92, 70)
    total = size * 1.02 * len(lines)
    y = (H - total) / 2 + size * 0.86
    for i, line in enumerate(lines):
        canvas.save()
        canvas.translate(x0, y)
        canvas.rotate(-3.0)
        last = i == len(lines) - 1
        canvas.drawString(line, 7, 8, font, skia.Paint(AntiAlias=True, Color=col((0, 0, 0), 150)))
        canvas.drawString(line, 0, 0, font, skia.Paint(AntiAlias=True, Color=col(INK), Style=skia.Paint.kStroke_Style, StrokeWidth=size * 0.14, StrokeJoin=skia.Paint.kRound_Join))
        canvas.drawString(line, 0, 0, font, skia.Paint(AntiAlias=True, Color=col(hl if last else (255, 255, 255))))
        canvas.restore()
        y += size * 1.02


def render(scenes, durations: List[float], title: str, out_path: Path, thumbnail_text: str = "") -> Path:
    """Render a 1280x720 JPEG. Raises on any problem so the pipeline can fall back to the legacy thumbnail."""
    dirs = direction.direct(scenes, durations, title)
    d = next((x for x in dirs if x.mood == "shocked"), None) or next((x for x in dirs if x.mood == "serious"), dirs[0])
    rng = random.Random(zlib.crc32(title.encode()))
    sset = build_set(d.setting, d.tod, W, H, rng)
    mood = "shocked" if d.mood != "serious" else "serious"
    u = H / 1080.0
    surface = skia.Surface(W, H)
    c = surface.getCanvas()
    hero_x, gy = W * 0.27, H * 0.97
    scale = 8.0 * u
    c.save()
    c.translate(hero_x, H * 0.5)
    c.scale(1.22, 1.22)
    c.translate(-hero_x, -H * 0.5)
    for L in sset.layers:
        if not L.front:
            off = -(L.image.width() - W) / 2
            c.drawImage(L.image, off, 0)
    c.restore()
    # sunburst behind the hero: the cheapest way to say "look HERE"
    cx, cy = hero_x, H * 0.46
    burst = (255, 196, 64) if mood == "shocked" else (230, 70, 60)
    for i in range(18):
        a0 = i * math.tau / 18
        a1 = a0 + math.tau / 36
        pts = [(cx, cy), (cx + math.cos(a0) * 1400, cy + math.sin(a0) * 1400), (cx + math.cos(a1) * 1400, cy + math.sin(a1) * 1400)]
        c.drawPath(skia.Path().moveTo(*pts[0]).lineTo(*pts[1]).lineTo(*pts[2]).close(), fill(burst, 70))
    shader = skia.GradientShader.MakeLinear([(W * 0.42, 0), (W * 0.62, 0)], [col((0, 0, 0), 0), col((8, 6, 20), 170)])
    c.drawRect(skia.Rect(0, 0, W, H), skia.Paint(Shader=shader))   # darken the text side
    look = d.hero if d.hero is not None else C.Look()
    pose = C.pose_shock(1.0, 0.5) if mood == "shocked" else C.pose_talk(1.2, 0.4)
    C.draw_shadow(c, hero_x, gy, scale)
    C.draw_character(c, look, pose, C.Face(mood=mood, mouth=0.9 if mood == "shocked" else 0.0), hero_x, gy, scale, 1)
    fx.draw_emote(c, "!" if mood == "shocked" else "?", hero_x + 170 * u, gy - 101 * scale - 20 * u, scale * 1.15, 0.6, 9.0)
    fx.draw_mascot(c, W * 0.93, H * 0.12, 2.6 * u, 1.0, "shocked", -0.8, 0.0, 0.0)
    _draw_caption(c, pick_text(title, thumbnail_text), W * 0.50, W * 0.965, mood)
    vshader = skia.GradientShader.MakeRadial((W / 2, H / 2), math.hypot(W, H) * 0.55, [col((0, 0, 0), 0), col((0, 0, 0), 0), col((6, 4, 18), 110)], [0, 0.6, 1])
    c.drawRect(skia.Rect(0, 0, W, H), skia.Paint(Shader=vshader))
    data = surface.makeImageSnapshot().encodeToData(skia.kJPEG, 90)
    out_path = Path(out_path)
    out_path.write_bytes(bytes(data))
    if out_path.stat().st_size > 1_900_000:
        out_path.write_bytes(bytes(surface.makeImageSnapshot().encodeToData(skia.kJPEG, 75)))
    return out_path
