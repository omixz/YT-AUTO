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
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw

from .config import PipelineConfig
from .script_writer import Scene

INK = (25, 25, 25)
SKY = (255, 255, 255)


# --- environment settings (ground + background elements) -------------------

_KEYWORD_TO_SETTING = [
    (("snow", "siberia", "arctic", "ice", "frozen", "winter", "cold", "blizzard"), "snow"),
    (("ocean", "sea", "beach", "coast", "island", "ship", "boat", "wave",
      "octopus", "squid", "cephalopod", "marine", "underwater", "aquatic",
      "deep-sea", "deep sea", "tentacle", "reef", "fish", "whale", "shark"), "water"),
    (("mountain", "valley", "cliff", "peak", "himalay", "andes", "alps"), "mountain"),
    (("war", "battle", "combat", "ruin", "rubble", "bomb", "wreckage", "crash"), "ruins"),
    (("forest", "jungle", "wood", "tree", "wilderness"), "forest"),
    (("desert", "sand", "sahara", "dune"), "desert"),
    (("room", "office", "lab", "laboratory", "indoor", "house", "building", "factory"), "indoor"),
]

GROUND_COLORS = {
    "snow": (238, 242, 245),
    "water": (150, 190, 210),
    "mountain": (200, 200, 190),
    "ruins": (190, 180, 165),
    "forest": (160, 195, 140),
    "desert": (225, 200, 150),
    "indoor": (210, 190, 160),
    "default": (200, 210, 190),
}


def _setting_for_scene(scene: Scene) -> str:
    haystack = f"{scene.narration} {' '.join(scene.visual_keywords)}".lower()
    for keywords, setting in _KEYWORD_TO_SETTING:
        if any(kw in haystack for kw in keywords):
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


_ELEMENT_DRAWERS = {
    "indoor": [_draw_house],
    "snow": [_draw_house, _draw_tree],
    "mountain": [_draw_mountain, _draw_tree],
    "ruins": [_draw_ruin],
    "forest": [_draw_tree, _draw_tree, _draw_house],
    "desert": [_draw_ruin],
    "water": [_draw_wave],
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
    (("died", "death", "killed", "dead", "disaster", "destroyed", "collapse", "vanished", "gone"), "shocked"),
    (("shock", "twist", "sudden", "surprise", "warning", "danger"), "shocked"),
]


def _match(scene: Scene, table) -> Optional[str]:
    haystack = f"{scene.narration} {' '.join(scene.visual_keywords)}".lower()
    for keywords, value in table:
        if any(kw in haystack for kw in keywords):
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


def draw_character(draw: ImageDraw.ImageDraw, rng: random.Random, cx: float, ground_y: float, scale: float, outfit: tuple, headwear: Optional[str], mood: str, pose: str = "sides") -> None:
    head_r = 95 * scale
    hip_y = ground_y - 210 * scale
    shoulder_y = hip_y - 225 * scale
    head_cy = shoulder_y - head_r * 1.15

    # legs
    _sketchy_polyline(draw, rng, [(cx - 52 * scale, hip_y), (cx - 60 * scale, ground_y)], width=int(20 * scale) or 4)
    _sketchy_polyline(draw, rng, [(cx + 52 * scale, hip_y), (cx + 60 * scale, ground_y)], width=int(20 * scale) or 4)

    # torso
    torso = [(cx - 80 * scale, shoulder_y), (cx + 80 * scale, shoulder_y), (cx + 62 * scale, hip_y), (cx - 62 * scale, hip_y)]
    _sketchy_polyline(draw, rng, torso, fill=outfit, close=True, width=int(11 * scale) or 4)

    # arms
    if pose == "raised":
        _sketchy_polyline(draw, rng, [(cx - 80 * scale, shoulder_y), (cx - 130 * scale, shoulder_y - 140 * scale)], width=int(18 * scale) or 4)
        _sketchy_polyline(draw, rng, [(cx + 80 * scale, shoulder_y), (cx + 130 * scale, shoulder_y - 140 * scale)], width=int(18 * scale) or 4)
    elif pose == "crossed":
        _sketchy_polyline(draw, rng, [(cx - 80 * scale, shoulder_y), (cx + 35 * scale, shoulder_y + 70 * scale)], width=int(18 * scale) or 4)
        _sketchy_polyline(draw, rng, [(cx + 80 * scale, shoulder_y), (cx - 35 * scale, shoulder_y + 70 * scale)], width=int(18 * scale) or 4)
    else:
        _sketchy_polyline(draw, rng, [(cx - 80 * scale, shoulder_y), (cx - 100 * scale, hip_y - 10 * scale)], width=int(18 * scale) or 4)
        _sketchy_polyline(draw, rng, [(cx + 80 * scale, shoulder_y), (cx + 100 * scale, hip_y - 10 * scale)], width=int(18 * scale) or 4)

    # head
    draw.ellipse([cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r], fill=(245, 210, 175), outline=INK, width=int(9 * scale) or 4)
    if mood == "shocked":
        _x_eyes(draw, cx, head_cy, spacing=head_r * 0.35, r=head_r * 0.16)
        _mouth(draw, cx, head_cy + head_r * 0.35, w=head_r * 0.4, up=False)
    else:
        _dot_eyes(draw, cx, head_cy, spacing=head_r * 0.35, r=head_r * 0.1)
        _mouth(draw, cx, head_cy + head_r * 0.35, w=head_r * 0.4, up=True)

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


def _draw_octopus(draw, rng, cx, cy, scale):
    body = (196, 84, 108)
    r = 150 * scale
    lw = int(8 * scale) or 4
    base_y = cy + r * 0.28

    # Eight tentacles fanning out below the mantle, drawn as an INK-outlined
    # stroke (thick dark line under a slightly thinner body-colour line) so
    # they read as solid limbs with an outline rather than flat sticks.
    n = 8
    for i in range(n):
        spread = (i / (n - 1) - 0.5) * 2  # -1 .. 1
        sx = cx + spread * r * 0.62
        mx = cx + spread * r * 1.35
        ex = cx + spread * r * 1.75
        wob = (1 if i % 2 == 0 else -1) * 22 * scale
        pts = [(sx, base_y), (mx, base_y + 120 * scale),
               (ex + wob, base_y + 210 * scale)]
        draw.line(pts, fill=INK, width=int(40 * scale) or 6, joint="curve")
    for i in range(n):
        spread = (i / (n - 1) - 0.5) * 2
        sx = cx + spread * r * 0.62
        mx = cx + spread * r * 1.35
        ex = cx + spread * r * 1.75
        wob = (1 if i % 2 == 0 else -1) * 22 * scale
        pts = [(sx, base_y), (mx, base_y + 120 * scale),
               (ex + wob, base_y + 210 * scale)]
        draw.line(pts, fill=body, width=int(28 * scale) or 4, joint="curve")
        tip = pts[-1]
        draw.ellipse([tip[0] - 16 * scale, tip[1] - 16 * scale,
                      tip[0] + 16 * scale, tip[1] + 16 * scale], fill=body, outline=INK, width=lw)

    # Mantle (bulbous head), drawn over the tentacle roots.
    draw.ellipse([cx - r, cy - r * 1.25, cx + r, cy + r * 0.55], fill=body, outline=INK, width=lw)

    # Eyes: white with a big pupil, the flat cartoon look.
    eye_r = r * 0.3
    for ex in (cx - r * 0.44, cx + r * 0.44):
        draw.ellipse([ex - eye_r, cy - eye_r * 1.2, ex + eye_r, cy + eye_r * 0.8],
                     fill=(255, 255, 255), outline=INK, width=lw)
        pr = eye_r * 0.5
        pcy = cy - eye_r * 0.1
        draw.ellipse([ex - pr, pcy - pr, ex + pr, pcy + pr], fill=INK)


def _draw_fish(draw, rng, cx, cy, scale):
    body = (235, 150, 60)
    r = 130 * scale
    lw = int(8 * scale) or 4
    # tail
    _outlined_blob(draw, [(cx - r * 1.05, cy), (cx - r * 1.7, cy - r * 0.6),
                          (cx - r * 1.7, cy + r * 0.6)], body, lw)
    # body
    draw.ellipse([cx - r * 1.1, cy - r * 0.72, cx + r * 1.1, cy + r * 0.72],
                 fill=body, outline=INK, width=lw)
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


_SEABED_PROPS = [_draw_seaweed, _draw_seaweed, _draw_coral, _draw_searock]

_KEYWORD_TO_SUBJECT = [
    (("octopus", "cephalopod", "tentacle", "mollusk", "kraken", "squid", "cuttlefish"), "octopus"),
    (("fish", "shark", "whale", "reef", "eel", "marine life", "sea creature"), "fish"),
]


def _subject_for_scene(scene: Scene) -> Optional[str]:
    return _match(scene, _KEYWORD_TO_SUBJECT)


def _dominant_subject(scenes: List[Scene], extra_text: str = "") -> Optional[str]:
    """A video about octopuses should show an octopus in *every* scene, even
    the ones whose narration happens not to say 'octopus' (e.g. a sentence
    about a protein). Pick the most common subject across the whole script
    (plus the title/topic) and use it as the per-scene fallback."""
    haystack = extra_text.lower() + " " + " ".join(
        f"{s.narration} {' '.join(s.visual_keywords)}" for s in scenes
    ).lower()
    counts = {}
    for keywords, subject in _KEYWORD_TO_SUBJECT:
        hits = sum(haystack.count(kw) for kw in keywords)
        if hits:
            counts[subject] = counts.get(subject, 0) + hits
    if not counts:
        return None
    return max(counts, key=counts.get)


# --- scene composition -----------------------------------------------------

def _draw_water_scene(draw, rng, w, h):
    """Fills the lower half of the frame with water (wavy surface + bubbles)
    and returns the surface y, so an aquatic subject can be placed below it."""
    surface_y = round(h * 0.24)
    draw.rectangle([0, surface_y, w, h], fill=(64, 132, 176))
    crest = []
    x = 0
    while x <= w:
        crest.append((x, surface_y + (15 if (x // 44) % 2 == 0 else -15)))
        x += 44
    draw.line(crest, fill=(200, 230, 242), width=6, joint="curve")
    for _ in range(round(w / 90)):
        bx = rng.uniform(0, w)
        by = rng.uniform(surface_y + 40, h - 30)
        br = rng.uniform(6, 18)
        draw.ellipse([bx - br, by - br, bx + br, by + br], outline=(190, 224, 238), width=3)
    return surface_y


def generate_scene_image(
    scene: Scene, index: int, config: PipelineConfig, work_dir: Path,
    subject_fallback: Optional[str] = None,
) -> Path:
    rng = random.Random(index)
    w, h = config.video.resolution
    img = Image.new("RGB", (w, h), SKY)
    draw = ImageDraw.Draw(img)

    subject = _subject_for_scene(scene) or subject_fallback

    if subject in _AQUATIC_SUBJECTS:
        # Underwater scene: water fills the lower frame, a seabed with a few
        # varied props runs along the bottom, and the subject is placed at a
        # per-scene position/size so consecutive scenes don't look identical.
        surface_y = _draw_water_scene(draw, rng, w, h)
        base_scale = h / 1080

        floor_y = h - round(40 * base_scale)
        draw.rectangle([0, floor_y, w, h], fill=(196, 178, 140))
        draw.line([(0, floor_y), (w, floor_y)], fill=INK, width=3)
        # 2-4 seabed props at spread-out x positions (skip the middle third so
        # they don't collide with the subject).
        n_props = rng.randint(2, 4)
        for _ in range(n_props):
            side = rng.choice([rng.uniform(0.04, 0.30), rng.uniform(0.70, 0.96)])
            rng.choice(_SEABED_PROPS)(draw, rng, w * side, floor_y, base_scale * rng.uniform(0.8, 1.25))

        subj_scale = base_scale * rng.uniform(1.0, 1.3)
        subj_cx = w * rng.uniform(0.34, 0.66)
        subj_cy = surface_y + (h - surface_y) * rng.uniform(0.34, 0.5)
        _SUBJECT_DRAWERS[subject](draw, rng, subj_cx, subj_cy, subj_scale)
        out_path = work_dir / f"scene_{index:02d}_illustration.jpg"
        img.save(out_path, quality=90)
        return out_path

    setting = _setting_for_scene(scene)
    ground_y = round(h * 0.82)
    draw.rectangle([0, ground_y, w, h], fill=GROUND_COLORS.get(setting, GROUND_COLORS["default"]))
    draw.line([(0, ground_y), (w, ground_y)], fill=INK, width=3)
    texture = _GROUND_TEXTURES.get(setting)
    if texture:
        texture(draw, rng, ground_y, w, h)

    element_scale = h / 1080
    drawers = _ELEMENT_DRAWERS.get(setting, _ELEMENT_DRAWERS["default"])
    # Alternate left/right of the centered focal element rather than picking
    # random positions, which too easily clustered every element on one
    # side and left the other half of the frame empty.
    left_positions = [w * 0.10, w * 0.24]
    right_positions = [w * 0.76, w * 0.90]
    li = ri = 0
    for i, drawer in enumerate(drawers):
        if i % 2 == 0 and li < len(left_positions):
            x = left_positions[li]
            li += 1
        elif ri < len(right_positions):
            x = right_positions[ri]
            ri += 1
        else:
            x = w * rng.uniform(0.1, 0.9)
        drawer(draw, rng, x, ground_y, element_scale * rng.uniform(0.9, 1.3))

    if subject in _SUBJECT_DRAWERS:
        # A land subject (non-aquatic) drawn as the focal element on the ground.
        _SUBJECT_DRAWERS[subject](draw, rng, w * 0.5, ground_y - 180 * element_scale, element_scale)
    else:
        outfit = _match(scene, _KEYWORD_TO_OUTFIT) or (150, 130, 110)
        headwear = _match(scene, _KEYWORD_TO_HEADWEAR)
        mood = _match(scene, _KEYWORD_TO_MOOD) or "neutral"
        pose = rng.choice(["sides", "raised", "crossed"]) if scene.role != "hook" else "raised"
        draw_character(draw, rng, w * 0.5, ground_y, element_scale, outfit, headwear, mood, pose)

    out_path = work_dir / f"scene_{index:02d}_illustration.jpg"
    img.save(out_path, quality=90)
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
