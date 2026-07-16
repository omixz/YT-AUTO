"""Generates one flat-vector-clipart illustration per scene, zero API cost.

This is the style the user actually approved (see the "Historical Events
That Never Actually Happened" reference thumbnail and the mockup2.png
prototype they signed off on): solid flat colors, thick black outlines, no
shading, simple circle heads with dot/X eyes and a curved-line mouth,
everyone bald or head-covered. illustration.py (AI image generation via
Pollinations) kept drifting back toward painterly/shaded output no matter
how the prompt was tuned - this sidesteps that entirely by drawing the
scene directly, matching the approved look every time.

Each scene gets a simple environment (ground + 0-3 background elements
picked by keyword) with one character - the environment is drawn first and
sized to fill the frame, since "show the setting, not just a face" was
explicit feedback; the character is a normal-sized part of that scene, not
a close-up portrait.
"""
from __future__ import annotations

import math
import random
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw

from .config import PipelineConfig
from .script_writer import Scene

INK = (25, 25, 25)
SKY = (255, 255, 255)


def _contains_keyword(haystack: str, keyword: str) -> bool:
    """Word-boundary-aware match for single-word keywords; plain substring
    match for multi-word phrases (which are collision-safe on their own).
    Bare substring matching on short single words was a real, wide-reaching
    bug: "ice" is a substring of "officer", "war" of "warning"/"warrior",
    "sand" of "thousand", "city" of "capacity"/"velocity", "cell" of
    "excellent" - all common words in historical narration, silently
    misrouting scenes to the wrong setting/subject/outfit."""
    if " " in keyword or "-" in keyword:
        return keyword in haystack
    return re.search(rf"\b{re.escape(keyword)}\b", haystack) is not None


def _count_keyword(haystack: str, keyword: str) -> int:
    if " " in keyword or "-" in keyword:
        return haystack.count(keyword)
    return len(re.findall(rf"\b{re.escape(keyword)}\b", haystack))


# --- environment settings (ground + background elements) -------------------

_KEYWORD_TO_SETTING = [
    (("snow", "siberia", "arctic", "ice", "frozen", "winter", "cold", "blizzard"), "snow"),
    (("ocean", "sea", "beach", "coast", "island", "ship", "boat", "wave", "submarine",
      "navy", "naval", "destroyer", "warship", "periscope", "fleet", "harbor",
      "octopus", "squid", "cephalopod", "marine", "underwater", "aquatic",
      "deep-sea", "deep sea", "tentacle", "reef", "fish", "whale", "shark"), "water"),
    (("mountain", "valley", "cliff", "peak", "himalay", "andes", "alps"), "mountain"),
    (("war", "battle", "combat", "trench", "front line", "rubble", "bomb",
      "wreckage", "crash", "invasion", "siege"), "ruins"),
    (("forest", "jungle", "wood", "tree", "wilderness"), "forest"),
    (("desert", "sand", "sahara", "dune"), "desert"),
    (("room", "office", "lab", "laboratory", "indoor", "house", "factory", "bunker", "cell"), "indoor"),
    (("palace", "throne", "castle", "fortress", "court", "coronation", "monarchy"), "palace"),
    (("temple", "pyramid", "tomb", "pharaoh", "sphinx", "ziggurat", "acropolis",
      "parthenon", "ancient egypt", "mesopotamia", "ruins of"), "ancient"),
    (("city", "street", "capital", "town square", "market", "urban", "metropolis"), "city"),
    (("olympus", "zeus", "poseidon", "hades", "underworld", "the gods", "god of",
      "goddess of", "pantheon", "valhalla", "asgard", "mythology", "mythical"), "mythic"),
]

GROUND_COLORS = {
    "snow": (238, 242, 245),
    "water": (150, 190, 210),
    "mountain": (200, 200, 190),
    "ruins": (190, 180, 165),
    "forest": (160, 195, 140),
    "desert": (225, 200, 150),
    "indoor": (210, 190, 160),
    "palace": (222, 210, 188),
    "ancient": (218, 198, 160),
    "city": (188, 192, 198),
    "mythic": (232, 222, 196),
    "default": (200, 210, 190),
}


def _setting_for_scene(scene: Scene) -> str:
    haystack = f"{scene.narration} {' '.join(scene.visual_keywords)}".lower()
    for keywords, setting in _KEYWORD_TO_SETTING:
        if any(_contains_keyword(haystack, kw) for kw in keywords):
            return setting
    return "default"


def _jitter(rng: random.Random, p: Tuple[float, float], amt: float = 2.0) -> Tuple[float, float]:
    return (p[0] + rng.uniform(-amt, amt), p[1] + rng.uniform(-amt, amt))


def _sketchy_polyline(draw: ImageDraw.ImageDraw, rng: random.Random, points, width=5, passes=2, close=False, fill=None):
    if fill:
        draw.polygon(points, fill=fill)
    pts = list(points) + ([points[0]] if close else [])
    for _ in range(passes):
        jittered = [_jitter(rng, p, 1.5) for p in pts]
        draw.line(jittered, fill=INK, width=width, joint="curve")


def _draw_house(draw: ImageDraw.ImageDraw, rng: random.Random, cx: float, base_y: float, scale: float, color=(120, 85, 60)) -> None:
    w, h = 360 * scale, 310 * scale
    body = [(cx - w / 2, base_y), (cx - w / 2, base_y - h), (cx + w / 2, base_y - h), (cx + w / 2, base_y)]
    _sketchy_polyline(draw, rng, body, fill=color, width=int(6 * scale) or 3)
    roof = [(cx - w / 2 - 35 * scale, base_y - h), (cx, base_y - h - 150 * scale), (cx + w / 2 + 35 * scale, base_y - h)]
    _sketchy_polyline(draw, rng, roof, fill=(90, 60, 45), close=True, width=int(6 * scale) or 3)
    win = [(cx - 65 * scale, base_y - h * 0.7), (cx - 65 * scale, base_y - h * 0.45),
           (cx + 10 * scale, base_y - h * 0.45), (cx + 10 * scale, base_y - h * 0.7)]
    _sketchy_polyline(draw, rng, win, fill=(210, 230, 240), close=True, width=int(4 * scale) or 3)
    door = [(cx + 60 * scale, base_y), (cx + 60 * scale, base_y - h * 0.5), (cx + 140 * scale, base_y - h * 0.5), (cx + 140 * scale, base_y)]
    _sketchy_polyline(draw, rng, door, fill=(70, 45, 35), width=int(4 * scale) or 3)


def _draw_mountain(draw: ImageDraw.ImageDraw, rng: random.Random, cx: float, base_y: float, scale: float, color=(150, 150, 155)) -> None:
    w, h = 640 * scale, 540 * scale
    peak = [(cx - w / 2, base_y), (cx - w * 0.1, base_y - h), (cx + w * 0.15, base_y - h * 0.55), (cx + w / 2, base_y)]
    _sketchy_polyline(draw, rng, peak, fill=color, close=True, width=int(6 * scale) or 3)
    cap = [(cx - w * 0.22, base_y - h * 0.78), (cx - w * 0.1, base_y - h), (cx + w * 0.02, base_y - h * 0.8)]
    _sketchy_polyline(draw, rng, cap, fill=(250, 250, 250), close=True, width=int(4 * scale) or 3)


def _draw_tree(draw: ImageDraw.ImageDraw, rng: random.Random, cx: float, base_y: float, scale: float) -> None:
    trunk_h = 100 * scale
    trunk = [(cx - 15 * scale, base_y), (cx - 15 * scale, base_y - trunk_h), (cx + 15 * scale, base_y - trunk_h), (cx + 15 * scale, base_y)]
    _sketchy_polyline(draw, rng, trunk, fill=(100, 70, 50), width=int(4 * scale) or 3)
    top_r = 90 * scale
    top_c = (cx, base_y - trunk_h - top_r * 0.7)
    pts = []
    for a in range(0, 360, 24):
        rad = math.radians(a)
        r = top_r + rng.uniform(-6, 6)
        pts.append((top_c[0] + r * math.cos(rad), top_c[1] + r * math.sin(rad)))
    _sketchy_polyline(draw, rng, pts, fill=(70, 130, 75), close=True, width=int(4 * scale) or 3)


def _draw_ruin(draw: ImageDraw.ImageDraw, rng: random.Random, cx: float, base_y: float, scale: float) -> None:
    w, h = 340 * scale, 260 * scale
    body = [(cx - w / 2, base_y), (cx - w / 2, base_y - h * 0.6), (cx - w * 0.1, base_y - h),
            (cx + w * 0.2, base_y - h * 0.5), (cx + w / 2, base_y - h * 0.7), (cx + w / 2, base_y)]
    _sketchy_polyline(draw, rng, body, fill=(140, 130, 120), close=True, width=int(6 * scale) or 3)
    for _ in range(3):
        rx = cx + rng.uniform(-w / 2, w / 2)
        ry = base_y - rng.uniform(0, 50 * scale)
        _sketchy_polyline(draw, rng, [(rx - 25, ry), (rx + 25, ry - 38), (rx + 65, ry)], width=int(4 * scale) or 3, fill=(110, 100, 95))


def _draw_wave(draw: ImageDraw.ImageDraw, rng: random.Random, cx: float, base_y: float, scale: float) -> None:
    pts = []
    for i in range(-3, 4):
        pts.append((cx + i * 40 * scale, base_y - (30 * scale if i % 2 == 0 else 5 * scale)))
    _sketchy_polyline(draw, rng, pts, width=4)


def _draw_temple(draw: ImageDraw.ImageDraw, rng: random.Random, cx: float, base_y: float, scale: float) -> None:
    """A simplified ancient temple: a triangular pediment over a row of
    columns - distinct silhouette from the house, for ancient/mythic scenes."""
    w, h = 380 * scale, 220 * scale
    col_w = w / 5
    for i in range(5):
        cx_i = cx - w / 2 + col_w * i + col_w / 2
        col = [(cx_i - col_w * 0.28, base_y), (cx_i - col_w * 0.28, base_y - h),
               (cx_i + col_w * 0.28, base_y - h), (cx_i + col_w * 0.28, base_y)]
        _sketchy_polyline(draw, rng, col, fill=(225, 215, 195), width=int(4 * scale) or 3)
    deck = [(cx - w / 2, base_y - h), (cx + w / 2, base_y - h), (cx + w / 2, base_y - h * 1.08), (cx - w / 2, base_y - h * 1.08)]
    _sketchy_polyline(draw, rng, deck, fill=(200, 190, 170), close=True, width=int(5 * scale) or 3)
    pediment = [(cx - w / 2 - 15 * scale, base_y - h * 1.08), (cx, base_y - h * 1.5), (cx + w / 2 + 15 * scale, base_y - h * 1.08)]
    _sketchy_polyline(draw, rng, pediment, fill=(190, 175, 150), close=True, width=int(5 * scale) or 3)


def _draw_castle(draw: ImageDraw.ImageDraw, rng: random.Random, cx: float, base_y: float, scale: float) -> None:
    w, h = 300 * scale, 260 * scale
    keep = [(cx - w * 0.3, base_y), (cx - w * 0.3, base_y - h * 0.75), (cx + w * 0.3, base_y - h * 0.75), (cx + w * 0.3, base_y)]
    _sketchy_polyline(draw, rng, keep, fill=(150, 145, 140), close=True, width=int(5 * scale) or 3)
    for side in (-1, 1):
        tx = cx + side * w * 0.42
        tower = [(tx - w * 0.12, base_y), (tx - w * 0.12, base_y - h), (tx + w * 0.12, base_y - h), (tx + w * 0.12, base_y)]
        _sketchy_polyline(draw, rng, tower, fill=(135, 130, 128), close=True, width=int(5 * scale) or 3)
        roof = [(tx - w * 0.15, base_y - h), (tx, base_y - h * 1.22), (tx + w * 0.15, base_y - h)]
        _sketchy_polyline(draw, rng, roof, fill=(120, 60, 60), close=True, width=int(4 * scale) or 3)
    flag = [(cx, base_y - h * 0.75), (cx, base_y - h * 0.95), (cx + w * 0.14, base_y - h * 0.88)]
    _sketchy_polyline(draw, rng, flag, fill=(200, 60, 60), close=True, width=int(3 * scale) or 3)


def _draw_city_building(draw: ImageDraw.ImageDraw, rng: random.Random, cx: float, base_y: float, scale: float) -> None:
    w = rng.uniform(150, 220) * scale
    h = rng.uniform(260, 420) * scale
    color = rng.choice([(150, 155, 165), (170, 165, 155), (140, 150, 150)])
    body = [(cx - w / 2, base_y), (cx - w / 2, base_y - h), (cx + w / 2, base_y - h), (cx + w / 2, base_y)]
    _sketchy_polyline(draw, rng, body, fill=color, close=True, width=int(5 * scale) or 3)
    rows, cols = 4, 3
    for r in range(rows):
        for c in range(cols):
            wx = cx - w * 0.36 + (w * 0.72) * c / (cols - 1)
            wy = base_y - h * 0.15 - (h * 0.7) * r / (rows - 1)
            wr = w * 0.06
            draw.rectangle([wx - wr, wy - wr, wx + wr, wy + wr], fill=(230, 225, 200))


_ELEMENT_DRAWERS = {
    "indoor": [_draw_house],
    "snow": [_draw_house, _draw_tree],
    "mountain": [_draw_mountain, _draw_tree],
    "ruins": [_draw_ruin],
    "forest": [_draw_tree, _draw_tree, _draw_house],
    "desert": [_draw_ruin],
    "water": [_draw_wave],
    "palace": [_draw_castle],
    "ancient": [_draw_temple],
    "city": [_draw_city_building, _draw_city_building],
    # mythic scenes already get floating sky clouds from the general
    # cloud-adding logic below (any non-indoor setting) - _draw_cloud takes
    # an independent (cx, cy) sky position, not the base_y ground-anchor
    # convention every _ELEMENT_DRAWERS entry uses, so it can't be listed here.
    "mythic": [_draw_temple],
    "default": [_draw_house, _draw_tree],
}


# --- character -----------------------------------------------------------

_KEYWORD_TO_OUTFIT = [
    (("soldier", "army", "military", "war", "troops", "combat"), (85, 95, 65)),
    (("king", "queen", "royal", "monarch", "emperor", "empress"), (110, 60, 130)),
    (("scientist", "engineer", "doctor", "lab", "research"), (230, 230, 230)),
    (("sailor", "ship", "navy", "captain", "boat"), (40, 60, 110)),
    (("farmer", "villager", "peasant", "worker"), (140, 100, 60)),
]

_KEYWORD_TO_HEADWEAR = [
    (("soldier", "army", "military", "war", "troops", "combat", "helmet"), "helmet"),
    (("king", "queen", "royal", "monarch", "emperor", "empress", "crown"), "crown"),
    (("detective", "spy", "noir", "crime", "gangster", "hat"), "hat"),
    (("scientist", "engineer", "doctor", "lab"), "cap"),
]

_KEYWORD_TO_MOOD = [
    (("died", "death", "killed", "dead", "disaster", "destroyed", "collapse", "collapsed",
      "collapsing", "vanished", "gone"), "shocked"),
    (("shock", "twist", "sudden", "surprise", "warning", "danger"), "shocked"),
]


def _match(scene: Scene, table) -> Optional[str]:
    haystack = f"{scene.narration} {' '.join(scene.visual_keywords)}".lower()
    for keywords, value in table:
        if any(_contains_keyword(haystack, kw) for kw in keywords):
            return value
    return None


def _dot_eyes(draw, cx, cy, spacing=13, r=4):
    draw.ellipse([cx - spacing - r, cy - r, cx - spacing + r, cy + r], fill=INK)
    draw.ellipse([cx + spacing - r, cy - r, cx + spacing + r, cy + r], fill=INK)


def _x_eyes(draw, cx, cy, spacing=13, r=6):
    line_w = max(3, round(r * 0.35))
    for ex in (cx - spacing, cx + spacing):
        draw.line([(ex - r, cy - r), (ex + r, cy + r)], fill=INK, width=line_w)
        draw.line([(ex - r, cy + r), (ex + r, cy - r)], fill=INK, width=line_w)


def _mouth(draw, cx, cy, w=20, up=True):
    line_w = max(3, round(w * 0.15))
    if up:
        draw.arc([cx - w, cy - w // 2, cx + w, cy + w], start=20, end=160, fill=INK, width=line_w)
    else:
        draw.arc([cx - w, cy - w, cx + w, cy + w // 2], start=200, end=340, fill=INK, width=line_w)


def _headwear_width(r: float) -> int:
    return max(4, round(r * 0.06))


# All headwear drawers take (draw, cx, head_cy, r) - head_cy is the head
# circle's own center, not its top edge, matching how _helmet's geometry
# (copied from animation.py's original working version) was already
# defined; earlier versions of the other three expected a "top of head"
# offset instead, which is why the helmet used to float free of the head.

def _crown(draw, cx, head_cy, r):
    top_y = head_cy - r
    pts = [(cx - r * 0.9, top_y), (cx - r * 0.55, top_y - r * 0.7), (cx - r * 0.2, top_y - r * 0.3),
           (cx, top_y - r * 0.9), (cx + r * 0.2, top_y - r * 0.3), (cx + r * 0.55, top_y - r * 0.7),
           (cx + r * 0.9, top_y)]
    draw.polygon(pts, fill=(230, 190, 60), outline=INK, width=_headwear_width(r))


def _tophat(draw, cx, head_cy, r):
    top_y = head_cy - r
    w = _headwear_width(r)
    draw.rectangle([cx - r * 0.5, top_y - r * 1.4, cx + r * 0.5, top_y], fill=(30, 30, 30), outline=INK, width=w)
    draw.ellipse([cx - r * 0.95, top_y - r * 0.18, cx + r * 0.95, top_y + r * 0.18], fill=(30, 30, 30), outline=INK, width=w)


def _helmet(draw, cx, head_cy, r):
    draw.pieslice([cx - r * 1.05, head_cy - r * 1.1, cx + r * 1.05, head_cy + r * 0.3], 180, 360, fill=(90, 100, 70), outline=INK, width=_headwear_width(r))


def _flat_cap(draw, cx, head_cy, r):
    # Bounding box anchored on head_cy (not "top of head" - see note above);
    # the pieslice's flat edge sits at the box's vertical center, so this
    # needs to dip below the head's top edge (head_cy - r) to actually rest
    # on the head instead of floating above it.
    draw.pieslice([cx - r * 1.0, head_cy - r * 1.05, cx + r * 1.0, head_cy - r * 0.05], 180, 360, fill=(80, 80, 90), outline=INK, width=_headwear_width(r))


_HEADWEAR_DRAWERS = {"crown": _crown, "hat": _tophat, "helmet": _helmet, "cap": _flat_cap}


def draw_character(draw: ImageDraw.ImageDraw, rng: random.Random, cx: float, ground_y: float, scale: float, outfit: tuple, headwear: Optional[str], mood: str, pose: str = "sides", phase: float = 0.0) -> None:
    head_r = 95 * scale
    hip_y = ground_y - 210 * scale
    shoulder_y = hip_y - 225 * scale
    head_cy = shoulder_y - head_r * 1.15

    # Idle weight-shift sway, driven by phase (one full cycle per loop):
    # legs swing gently opposite each other and arms swing opposite the
    # legs, like a person shifting weight in place rather than a frozen
    # mannequin - the sprite-frame loop in generate_scene_clip renders this
    # across a handful of phases so the character actually moves.
    leg_swing = math.sin(phase) * 14 * scale
    arm_swing = math.sin(phase + math.pi) * 10 * scale

    # legs
    _sketchy_polyline(draw, rng, [(cx - 52 * scale, hip_y), (cx - 60 * scale + leg_swing, ground_y)], width=int(20 * scale) or 4)
    _sketchy_polyline(draw, rng, [(cx + 52 * scale, hip_y), (cx + 60 * scale - leg_swing, ground_y)], width=int(20 * scale) or 4)

    # torso
    torso = [(cx - 80 * scale, shoulder_y), (cx + 80 * scale, shoulder_y), (cx + 62 * scale, hip_y), (cx - 62 * scale, hip_y)]
    _sketchy_polyline(draw, rng, torso, fill=outfit, close=True, width=int(11 * scale) or 4)

    # arms
    if pose == "raised":
        _sketchy_polyline(draw, rng, [(cx - 80 * scale, shoulder_y), (cx - 130 * scale + arm_swing, shoulder_y - 140 * scale)], width=int(18 * scale) or 4)
        _sketchy_polyline(draw, rng, [(cx + 80 * scale, shoulder_y), (cx + 130 * scale + arm_swing, shoulder_y - 140 * scale)], width=int(18 * scale) or 4)
    elif pose == "crossed":
        _sketchy_polyline(draw, rng, [(cx - 80 * scale, shoulder_y), (cx + 35 * scale, shoulder_y + 70 * scale)], width=int(18 * scale) or 4)
        _sketchy_polyline(draw, rng, [(cx + 80 * scale, shoulder_y), (cx - 35 * scale, shoulder_y + 70 * scale)], width=int(18 * scale) or 4)
    else:
        _sketchy_polyline(draw, rng, [(cx - 80 * scale, shoulder_y), (cx - 100 * scale + arm_swing, hip_y - 10 * scale)], width=int(18 * scale) or 4)
        _sketchy_polyline(draw, rng, [(cx + 80 * scale, shoulder_y), (cx + 100 * scale - arm_swing, hip_y - 10 * scale)], width=int(18 * scale) or 4)

    # head
    skin = (245, 210, 175)
    draw.ellipse([cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r], fill=skin, outline=INK, width=int(9 * scale) or 4)
    _highlight_ellipse(draw, cx - head_r * 0.32, head_cy - head_r * 0.38, head_r * 0.28, head_r * 0.2, skin)
    brow_w = max(3, round(head_r * 0.05))
    # A brief closed-eyes blink once per loop cycle, instead of eyes that
    # never move at all across the whole scene.
    blinking = mood != "shocked" and (phase % (2 * math.pi)) < 0.3
    if mood == "shocked":
        _x_eyes(draw, cx, head_cy, spacing=head_r * 0.35, r=head_r * 0.16)
        _mouth(draw, cx, head_cy + head_r * 0.35, w=head_r * 0.4, up=False)
        for ex in (cx - head_r * 0.35, cx + head_r * 0.35):
            draw.line([(ex - head_r * 0.2, head_cy - head_r * 0.32), (ex + head_r * 0.2, head_cy - head_r * 0.42)],
                      fill=INK, width=brow_w)
    elif blinking:
        for ex in (cx - head_r * 0.35, cx + head_r * 0.35):
            draw.line([(ex - head_r * 0.1, head_cy), (ex + head_r * 0.1, head_cy)], fill=INK, width=brow_w)
        _mouth(draw, cx, head_cy + head_r * 0.35, w=head_r * 0.4, up=True)
        for ex in (cx - head_r * 0.35, cx + head_r * 0.35):
            draw.arc([ex - head_r * 0.2, head_cy - head_r * 0.42, ex + head_r * 0.2, head_cy - head_r * 0.22],
                      start=200, end=340, fill=INK, width=brow_w)
    else:
        _dot_eyes(draw, cx, head_cy, spacing=head_r * 0.35, r=head_r * 0.1)
        _mouth(draw, cx, head_cy + head_r * 0.35, w=head_r * 0.4, up=True)
        for ex in (cx - head_r * 0.35, cx + head_r * 0.35):
            draw.arc([ex - head_r * 0.2, head_cy - head_r * 0.42, ex + head_r * 0.2, head_cy - head_r * 0.22],
                      start=200, end=340, fill=INK, width=brow_w)

    if headwear and headwear in _HEADWEAR_DRAWERS:
        _HEADWEAR_DRAWERS[headwear](draw, cx, head_cy, head_r)


# --- ground texture (grass/snow/concrete/sand/rock, by setting) -----------

def _texture_grass(draw, rng, ground_y, w, h):
    for _ in range(round(w / 26)):
        x = rng.uniform(0, w)
        y = rng.uniform(ground_y + 10, h - 10)
        blade_h = rng.uniform(10, 22)
        draw.line([(x, y), (x - 5, y - blade_h)], fill=(90, 150, 80), width=3)
        draw.line([(x, y), (x + 5, y - blade_h)], fill=(90, 150, 80), width=3)


def _texture_snow(draw, rng, ground_y, w, h):
    for _ in range(round(w / 22)):
        x = rng.uniform(0, w)
        y = rng.uniform(ground_y + 8, h - 8)
        r = rng.uniform(3, 7)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(220, 228, 232))


def _texture_concrete(draw, rng, ground_y, w, h):
    step = round(w / 9)
    for x in range(step, w, step):
        draw.line([(x, ground_y), (x, h)], fill=(160, 160, 155), width=3)
    mid_y = ground_y + (h - ground_y) * 0.55
    draw.line([(0, mid_y), (w, mid_y)], fill=(160, 160, 155), width=3)


def _texture_sand(draw, rng, ground_y, w, h):
    for _ in range(round(w / 60)):
        x = rng.uniform(0, w - 60)
        y = rng.uniform(ground_y + 10, h - 15)
        draw.arc([x, y, x + 60, y + 20], start=0, end=180, fill=(200, 175, 130), width=3)


def _texture_rock(draw, rng, ground_y, w, h):
    for _ in range(round(w / 70)):
        x = rng.uniform(0, w)
        y = rng.uniform(ground_y + 10, h - 15)
        r = rng.uniform(8, 16)
        draw.ellipse([x - r, y - r * 0.6, x + r, y + r * 0.6], outline=(120, 115, 110), width=3)


def _draw_cloud(draw, rng, cx, cy, scale):
    color = (235, 238, 242)
    r = 46 * scale
    for dx, dy, rr in ((-1.1, 0.15, 0.85), (-0.4, -0.2, 1.0), (0.4, 0.0, 0.95), (1.1, 0.2, 0.75)):
        rad = r * rr
        draw.ellipse([cx + dx * r * 1.3 - rad, cy + dy * r - rad,
                      cx + dx * r * 1.3 + rad, cy + dy * r + rad], fill=color, outline=INK, width=max(3, round(3 * scale)))


_GROUND_TEXTURES = {
    "snow": _texture_snow,
    "forest": _texture_grass,
    "indoor": _texture_concrete,
    "desert": _texture_sand,
    "mountain": _texture_rock,
    "ruins": _texture_rock,
    "default": _texture_grass,
}


# --- subjects (the actual thing the video is about) ------------------------
#
# The character above is the right focal element for people-driven topics
# (a king, a soldier, a missing pilot), but a video *about an octopus* should
# show an octopus, not a person standing near it. When a scene's subject is a
# specific creature/object, it's drawn as the focal element instead of the
# human - "when talking about the ocean, show water and an octopus."

def _outlined_blob(draw, points, fill, line_w):
    """Filled polygon with a thick INK outline - the flat-vector look."""
    draw.polygon(points, fill=fill)
    draw.line(list(points) + [points[0]], fill=INK, width=line_w, joint="curve")


def _lighten(color, amount=0.35):
    return tuple(round(c + (255 - c) * amount) for c in color)


def _highlight_ellipse(draw, cx, cy, rx, ry, base_color):
    """A soft flat highlight patch (lighter flat ellipse, no gradient) for a
    touch of dimensionality while staying in the flat-vector style - the
    same trick a lot of flat-icon sets use instead of real shading."""
    draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=_lighten(base_color))


def _draw_octopus(draw, rng, cx, cy, scale, phase=0.0):
    body = (196, 84, 108)
    r = 150 * scale
    lw = int(8 * scale) or 4
    base_y = cy + r * 0.28

    # Eight tentacles fanning below the mantle. `phase` (radians) modulates
    # each tentacle's sway independently so an animation loop over several
    # phase values reads as the tentacles drifting, not just the whole
    # creature translating - see generate_scene_clip's aquatic sprite loop.
    n = 8
    for pass_fill, pass_width in ((INK, int(40 * scale) or 6), (body, int(28 * scale) or 4)):
        for i in range(n):
            spread = (i / (n - 1) - 0.5) * 2  # -1 .. 1
            sx = cx + spread * r * 0.62
            mx = cx + spread * r * 1.35
            wob = math.sin(phase * 1.6 + i * 0.85) * 26 * scale
            ex = cx + spread * r * 1.75
            pts = [(sx, base_y), (mx + wob * 0.5, base_y + 120 * scale),
                   (ex + wob, base_y + 210 * scale)]
            draw.line(pts, fill=pass_fill, width=pass_width, joint="curve")
            if pass_fill == body:
                tip = pts[-1]
                draw.ellipse([tip[0] - 16 * scale, tip[1] - 16 * scale,
                              tip[0] + 16 * scale, tip[1] + 16 * scale], fill=body, outline=INK, width=lw)

    # Mantle (bulbous head), drawn over the tentacle roots.
    draw.ellipse([cx - r, cy - r * 1.25, cx + r, cy + r * 0.55], fill=body, outline=INK, width=lw)
    _highlight_ellipse(draw, cx - r * 0.32, cy - r * 0.85, r * 0.32, r * 0.22, body)

    # Eyes: white with a big pupil, the flat cartoon look.
    eye_r = r * 0.3
    for ex in (cx - r * 0.44, cx + r * 0.44):
        draw.ellipse([ex - eye_r, cy - eye_r * 1.2, ex + eye_r, cy + eye_r * 0.8],
                     fill=(255, 255, 255), outline=INK, width=lw)
        pr = eye_r * 0.5
        pcy = cy - eye_r * 0.1
        draw.ellipse([ex - pr, pcy - pr, ex + pr, pcy + pr], fill=INK)


def _draw_fish(draw, rng, cx, cy, scale, phase=0.0):
    body = (235, 150, 60)
    r = 130 * scale
    lw = int(8 * scale) or 4
    tail_wag = math.sin(phase * 2.2) * 14 * scale
    # tail
    _outlined_blob(draw, [(cx - r * 1.05, cy), (cx - r * 1.7, cy - r * 0.6 + tail_wag),
                          (cx - r * 1.7, cy + r * 0.6 + tail_wag)], body, lw)
    # body
    draw.ellipse([cx - r * 1.1, cy - r * 0.72, cx + r * 1.1, cy + r * 0.72],
                 fill=body, outline=INK, width=lw)
    _highlight_ellipse(draw, cx + r * 0.1, cy - r * 0.34, r * 0.35, r * 0.18, body)
    # top fin
    _outlined_blob(draw, [(cx - r * 0.3, cy - r * 0.7), (cx + r * 0.2, cy - r * 1.15),
                          (cx + r * 0.45, cy - r * 0.65)], body, lw)
    # eye
    eye_r = r * 0.2
    ex = cx + r * 0.55
    draw.ellipse([ex - eye_r, cy - r * 0.35 - eye_r, ex + eye_r, cy - r * 0.35 + eye_r],
                 fill=(255, 255, 255), outline=INK, width=lw)
    pr = eye_r * 0.5
    draw.ellipse([ex - pr, cy - r * 0.35 - pr, ex + pr, cy - r * 0.35 + pr], fill=INK)


_SUBJECT_DRAWERS = {"octopus": _draw_octopus, "fish": _draw_fish}

# Subjects that live in water, so their scenes render an underwater backdrop.
_AQUATIC_SUBJECTS = {"octopus", "fish"}


def _draw_seaweed(draw, rng, base_x, floor_y, scale):
    """A wavy seaweed strand rising from the seabed."""
    color = (54, 132, 96)
    h = rng.uniform(180, 340) * scale
    segs = 6
    pts = [(base_x, floor_y)]
    for i in range(1, segs + 1):
        sway = math.sin(i * 1.1 + rng.uniform(0, 2)) * 34 * scale
        pts.append((base_x + sway, floor_y - h * i / segs))
    draw.line(pts, fill=color, width=int(20 * scale) or 5, joint="curve")


def _draw_coral(draw, rng, base_x, floor_y, scale):
    color = rng.choice([(224, 122, 95), (210, 150, 80), (200, 100, 130)])
    lw = int(7 * scale) or 4
    for _ in range(3):
        ang = rng.uniform(-0.6, 0.6)
        length = rng.uniform(90, 150) * scale
        tip = (base_x + math.sin(ang) * length, floor_y - math.cos(ang) * length)
        draw.line([(base_x, floor_y), tip], fill=color, width=int(22 * scale) or 5, joint="curve")
        draw.ellipse([tip[0] - 14 * scale, tip[1] - 14 * scale,
                      tip[0] + 14 * scale, tip[1] + 14 * scale], fill=color, outline=INK, width=lw)


def _draw_searock(draw, rng, base_x, floor_y, scale):
    w = rng.uniform(120, 220) * scale
    h = rng.uniform(50, 90) * scale
    pts = [(base_x - w / 2, floor_y), (base_x - w * 0.3, floor_y - h),
           (base_x + w * 0.1, floor_y - h * 1.2), (base_x + w * 0.4, floor_y - h * 0.6),
           (base_x + w / 2, floor_y)]
    _outlined_blob(draw, pts, (120, 120, 130), int(6 * scale) or 4)


def _draw_starfish(draw, rng, base_x, floor_y, scale):
    color = (230, 150, 60)
    r = rng.uniform(30, 48) * scale
    cy = floor_y - r * 0.5
    pts = []
    for i in range(10):
        ang = math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.42
        pts.append((base_x + rad * math.cos(ang), cy - rad * math.sin(ang)))
    _outlined_blob(draw, pts, color, int(5 * scale) or 3)


_SEABED_PROPS = [_draw_seaweed, _draw_seaweed, _draw_coral, _draw_searock, _draw_starfish]

_KEYWORD_TO_SUBJECT = [
    (("octopus", "cephalopod", "tentacle", "mollusk", "kraken", "squid", "cuttlefish"), "octopus"),
    (("fish", "shark", "whale", "reef", "eel", "marine life", "sea creature"), "fish"),
]


def _subject_for_scene(scene: Scene) -> Optional[str]:
    return _match(scene, _KEYWORD_TO_SUBJECT)


def _dominant_subject(scenes: List[Scene], extra_text: str = "") -> Optional[str]:
    """A video about octopuses should show an octopus regularly, even in
    scenes whose narration happens not to say 'octopus' (e.g. a sentence
    about a protein). Pick the most common subject across the whole script
    (plus the title/topic) and use it as the per-scene fallback."""
    haystack = extra_text.lower() + " " + " ".join(
        f"{s.narration} {' '.join(s.visual_keywords)}" for s in scenes
    ).lower()
    counts = {}
    for keywords, subject in _KEYWORD_TO_SUBJECT:
        hits = sum(_count_keyword(haystack, kw) for kw in keywords)
        if hits:
            counts[subject] = counts.get(subject, 0) + hits
    if not counts:
        return None
    return max(counts, key=counts.get)


def _resolve_subject(scene: Scene, index: int, subject_fallback: Optional[str]) -> Optional[str]:
    """A scene's own keywords always win. Failing that, the whole-video
    fallback subject only applies to *half* the remaining scenes (odd/even
    by index) rather than every single one - applying it everywhere is what
    caused "the same fish in every frame" for a whole video, since most
    scenes in a real script don't literally re-mention the subject by name.
    The other half fall through to the ordinary environment/character scene
    (still driven by that scene's own setting keywords), which is a
    genuinely different visual, not just a repositioned creature."""
    matched = _subject_for_scene(scene)
    if matched:
        return matched
    if subject_fallback and index % 2 == 0:
        return subject_fallback
    return None


# --- scene composition -----------------------------------------------------

def _draw_water_scene(draw, rng, w, h):
    """Water covers the entire frame (no white sky strip) - a lighter-to-
    darker vertical gradient reads as depth, with a bright ripple band near
    the very top standing in for the surface instead of a hard boundary to
    white. Returns a nominal surface_y (used to bias where the subject and
    static bubbles are placed - still "near the top" - even though water
    now fills the whole canvas)."""
    top_color = (118, 184, 212)
    bottom_color = (26, 64, 102)
    step = 4
    for y in range(0, h, step):
        t = y / h
        r = round(top_color[0] + (bottom_color[0] - top_color[0]) * t)
        g = round(top_color[1] + (bottom_color[1] - top_color[1]) * t)
        b = round(top_color[2] + (bottom_color[2] - top_color[2]) * t)
        draw.rectangle([0, y, w, y + step], fill=(r, g, b))

    surface_y = round(h * 0.06)
    crest = []
    x = 0
    while x <= w:
        crest.append((x, surface_y + (10 if (x // 44) % 2 == 0 else -10)))
        x += 44
    draw.line(crest, fill=(210, 236, 246), width=5, joint="curve")

    for _ in range(round(w / 70)):
        bx = rng.uniform(0, w)
        by = rng.uniform(surface_y + 20, h - 20)
        br = rng.uniform(5, 16)
        draw.ellipse([bx - br, by - br, bx + br, by + br], outline=(200, 230, 242), width=3)
    return surface_y


def _compose_scene(rng, scene: Scene, config: PipelineConfig, subject: Optional[str]):
    """Draws the background (everything except the focal subject) onto a fresh
    image and returns (background, paint_subject, motion).

    - paint_subject(draw) renders the subject onto any draw context, so the
      same composition can be flattened into a still or drawn onto its own
      transparent layer for animation.
    - motion is (amp_x, amp_y, period_x, period_y): how the subject drifts,
      used by the animator. Aquatic subjects float in two axes; land subjects
      bob gently in place.
    """
    w, h = config.video.resolution
    base = Image.new("RGB", (w, h), SKY)
    draw = ImageDraw.Draw(base)
    base_scale = h / 1080

    if subject in _AQUATIC_SUBJECTS:
        surface_y = _draw_water_scene(draw, rng, w, h)
        floor_y = h - round(40 * base_scale)
        draw.rectangle([0, floor_y, w, h], fill=(196, 178, 140))
        draw.line([(0, floor_y), (w, floor_y)], fill=INK, width=3)
        n_props = rng.randint(2, 4)
        for _ in range(n_props):
            side = rng.choice([rng.uniform(0.04, 0.30), rng.uniform(0.70, 0.96)])
            rng.choice(_SEABED_PROPS)(draw, rng, w * side, floor_y, base_scale * rng.uniform(0.8, 1.25))

        subj_scale = base_scale * rng.uniform(1.0, 1.3)
        subj_cx = w * rng.uniform(0.34, 0.66)
        subj_cy = surface_y + (h - surface_y) * rng.uniform(0.34, 0.5)
        drawer = _SUBJECT_DRAWERS[subject]

        def paint(d, phase=0.0):
            drawer(d, rng, subj_cx, subj_cy, subj_scale, phase)

        motion = (26 * base_scale, 30 * base_scale, 7.0, 3.7)
        return base, paint, motion

    setting = _setting_for_scene(scene)
    ground_y = round(h * 0.82)

    # A couple of flat clouds in the sky band above the ground - otherwise
    # that whole upper region is empty white, which reads as unfinished.
    if setting != "indoor":
        for _ in range(rng.randint(1, 2)):
            cx = w * rng.uniform(0.08, 0.92)
            cy = h * rng.uniform(0.10, 0.34)
            _draw_cloud(draw, rng, cx, cy, base_scale * rng.uniform(0.8, 1.2))

    draw.rectangle([0, ground_y, w, h], fill=GROUND_COLORS.get(setting, GROUND_COLORS["default"]))
    draw.line([(0, ground_y), (w, ground_y)], fill=INK, width=3)
    texture = _GROUND_TEXTURES.get(setting)
    if texture:
        texture(draw, rng, ground_y, w, h)

    element_scale = base_scale
    drawers = _ELEMENT_DRAWERS.get(setting, _ELEMENT_DRAWERS["default"])
    left_positions = [w * 0.10, w * 0.24]
    right_positions = [w * 0.76, w * 0.90]
    li = ri = 0
    for i, drawer in enumerate(drawers):
        if i % 2 == 0 and li < len(left_positions):
            x = left_positions[li]; li += 1
        elif ri < len(right_positions):
            x = right_positions[ri]; ri += 1
        else:
            x = w * rng.uniform(0.1, 0.9)
        drawer(draw, rng, x, ground_y, element_scale * rng.uniform(0.9, 1.3))

    if subject in _SUBJECT_DRAWERS:
        sd = _SUBJECT_DRAWERS[subject]

        def paint(d, phase=0.0):
            sd(d, rng, w * 0.5, ground_y - 180 * element_scale, element_scale, phase)
    else:
        outfit = _match(scene, _KEYWORD_TO_OUTFIT) or (150, 130, 110)
        headwear = _match(scene, _KEYWORD_TO_HEADWEAR)
        mood = _match(scene, _KEYWORD_TO_MOOD) or "neutral"
        pose = rng.choice(["sides", "raised", "crossed"]) if scene.role != "hook" else "raised"

        def paint(d, phase=0.0):
            draw_character(d, rng, w * 0.5, ground_y, element_scale, outfit, headwear, mood, pose, phase)

    motion = (0.0, 12 * base_scale, 0.0, 2.6)  # gentle in-place bob
    return base, paint, motion


def generate_scene_image(
    scene: Scene, index: int, config: PipelineConfig, work_dir: Path,
    subject_fallback: Optional[str] = None,
) -> Path:
    rng = random.Random(index)
    subject = _resolve_subject(scene, index, subject_fallback)
    base, paint, _motion = _compose_scene(rng, scene, config, subject)
    paint(ImageDraw.Draw(base))
    out_path = work_dir / f"scene_{index:02d}_illustration.jpg"
    base.save(out_path, quality=90)
    return out_path


# --- aquatic sprite loop: tentacle-sway + rising bubbles -------------------
# A single static overlay PNG only lets the whole creature drift as a rigid
# body. To get real tentacle-sway and bubbles rising independently, aquatic
# subjects instead get a short (2s) looping alpha-video sprite - a handful
# of Pillow-rendered frames encoded to VP9/yuva420p - which is then looped
# for the whole scene duration via ffmpeg, same overlay mechanism as before.

_LOOP_SECONDS = 2.0
_LOOP_FPS = 8
_LOOP_FRAMES = int(_LOOP_SECONDS * _LOOP_FPS)


def _rising_bubbles(rng: random.Random, w: int, h: int, n: int = 9) -> list:
    return [
        {
            "x": rng.uniform(w * 0.08, w * 0.92),
            "y0": rng.uniform(0, h),
            "speed": rng.uniform(35, 85),  # px/sec
            "r": rng.uniform(4, 11),
        }
        for _ in range(n)
    ]


def _draw_bubbles(draw: ImageDraw.ImageDraw, bubbles: list, t: float, h: int) -> None:
    for b in bubbles:
        y = (b["y0"] - b["speed"] * t) % h
        r = b["r"]
        draw.ellipse([b["x"] - r, y - r, b["x"] + r, y + r], outline=(215, 238, 248), width=3)


def _build_sprite_frames(rng: random.Random, paint, w: int, h: int, work_dir: Path, index: int, bubbles: bool = False) -> Path:
    """Writes the looping RGBA frame sequence to disk and returns its
    printf-style pattern path. Fed straight into ffmpeg's image2 demuxer
    (with -stream_loop) rather than pre-encoded to a video, since VP9's
    alpha channel is lossy through some libvpx builds (alt-ref frames can
    silently drop it, rendering the "transparent" areas as opaque black) -
    a raw PNG sequence has no such risk and every ffmpeg build reads it.

    Used for any subject/character whose `paint` callback varies by phase -
    aquatic creatures (tentacle-sway/fin-wiggle, plus rising bubbles) and the
    land character (idle weight-shift + blink) alike - not just aquatic ones,
    since a rigid static PNG was the single biggest source of "this looks
    like a slideshow" for every character-driven scene."""
    frame_dir = work_dir / f"scene_{index:02d}_frames"
    frame_dir.mkdir(exist_ok=True)
    bubble_specs = _rising_bubbles(rng, w, h) if bubbles else None

    for i in range(_LOOP_FRAMES):
        t = i / _LOOP_FPS
        phase = 2 * math.pi * i / _LOOP_FRAMES
        frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(frame)
        if bubble_specs is not None:
            _draw_bubbles(d, bubble_specs, t, h)
        paint(d, phase)
        frame.save(frame_dir / f"f_{i:03d}.png")

    return frame_dir / "f_%03d.png"


def generate_scene_clip(
    scene: Scene, index: int, config: PipelineConfig, work_dir: Path,
    duration: float, subject_fallback: Optional[str] = None,
) -> Path:
    """Renders an animated MP4 for one scene: a slow Ken Burns pan/zoom across
    the background (every scene, subject or not - a scene with no subject
    used to just be a single frozen frame for its whole duration, which was
    the single biggest source of "this looks bland"), plus the subject drawn
    on its own layer and drifted over time via an ffmpeg overlay with
    time-varying position, so the figure floats/bobs instead of sitting
    still. Aquatic subjects additionally get a short looping alpha-video
    sprite (tentacle-sway/fin-wiggle + rising bubbles - see
    _build_aquatic_sprite_loop) instead of a single static PNG, so the
    creature itself has motion, not just its position. Cheap either way -
    a handful of small frames or one encode, no per-frame full-scene
    rendering."""
    rng = random.Random(index)
    w, h = config.video.resolution
    subject = _resolve_subject(scene, index, subject_fallback)
    base, paint, (ax, ay, px, py) = _compose_scene(rng, scene, config, subject)

    bg_path = work_dir / f"scene_{index:02d}_bg.jpg"
    base.save(bg_path, quality=90)

    if subject in _AQUATIC_SUBJECTS or subject is None:
        # Aquatic creatures and the plain land character both have a
        # phase-varying paint() (tentacle-sway/blink respectively), so both
        # render as a looping animated frame sequence rather than one frozen
        # pose. Other subject drawers (none currently non-aquatic) fall
        # through to the static sprite below.
        frame_pattern = _build_sprite_frames(rng, paint, w, h, work_dir, index, bubbles=subject in _AQUATIC_SUBJECTS)
        sprite_input = ["-framerate", str(_LOOP_FPS), "-stream_loop", "-1", "-i", str(frame_pattern)]
    else:
        sprite = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        paint(ImageDraw.Draw(sprite))
        sprite_path = work_dir / f"scene_{index:02d}_sprite.png"
        sprite.save(sprite_path)
        sprite_input = ["-loop", "1", "-i", str(sprite_path)]

    # Ken Burns: render the background oversized and slide/zoom a w x h
    # window across it over the scene's duration, instead of feeding the
    # native-resolution still straight through. Direction/axis/zoom amount
    # are seeded per-scene (rng, and index parity for direction) so
    # consecutive scenes don't all crawl the same way.
    zoom = rng.uniform(1.10, 1.22)
    ow, oh = round(w * zoom), round(h * zoom)
    max_dx, max_dy = ow - w, oh - h
    horizontal = rng.random() < 0.7  # horizontal pans read better than vertical most of the time
    forward = index % 2 == 0
    safe_duration = max(duration, 0.01)
    if horizontal:
        bg_x = f"{max_dx:.1f}*(t/{safe_duration:.3f})" if forward else f"{max_dx:.1f}*(1-t/{safe_duration:.3f})"
        bg_y = f"{max_dy / 2:.1f}"
    else:
        bg_x = f"{max_dx / 2:.1f}"
        bg_y = f"{max_dy:.1f}*(t/{safe_duration:.3f})" if forward else f"{max_dy:.1f}*(1-t/{safe_duration:.3f})"

    subj_x = f"{ax:.1f}*sin(2*PI*t/{px})" if ax and px else "0"
    subj_y = f"{ay:.1f}*sin(2*PI*t/{py})" if ay and py else "0"
    out_path = work_dir / f"scene_{index:02d}_anim.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(bg_path),
        *sprite_input,
        "-filter_complex",
        f"[0:v]scale={ow}:{oh},fps={config.video.fps},"
        f"crop=w={w}:h={h}:x='{bg_x}':y='{bg_y}'[bg];"
        f"[bg][1:v]overlay=x={subj_x}:y={subj_y}:eval=frame[v]",
        "-map", "[v]", "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"scene animation ffmpeg failed:\n{' '.join(cmd)}\n\n{result.stderr[-3000:]}")
    return out_path


def generate_all(scenes: List[Scene], config: PipelineConfig, work_dir: Path) -> List[Path]:
    # Fallback subject from the whole script so a single-subject video (e.g.
    # about an octopus) shows it consistently, not only on sentences that
    # name it. Title lives on the Script, which we don't have here, but the
    # scenes' combined text is a good enough signal.
    fallback = _dominant_subject(scenes)
    return [
        generate_scene_image(scene, i, config, work_dir, subject_fallback=fallback)
        for i, scene in enumerate(scenes)
    ]


def generate_all_clips(
    scenes: List[Scene], durations: List[float], config: PipelineConfig, work_dir: Path
) -> List[Path]:
    """Animated per-scene clips (one MP4 each), sized to each scene's audio
    duration. Same subject/fallback logic as generate_all."""
    fallback = _dominant_subject(scenes)
    return [
        generate_scene_clip(scene, i, config, work_dir, dur, subject_fallback=fallback)
        for i, (scene, dur) in enumerate(zip(scenes, durations))
    ]
