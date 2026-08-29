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

# draw_character's raw geometry (see its own docstring/comment for the math)
# comes out taller than a house at scale=1.0 - this brings it down to
# roughly person-sized against the environment drawers below, which weren't
# touched and still use element_scale directly.
HUMAN_SCALE = 0.5


def _contains_keyword(haystack: str, keyword: str) -> bool:
    """Word-boundary-aware match for single-word keywords; plain substring
    match for multi-word phrases (which are collision-safe on their own).
    Bare substring matching on short single words was a real, wide-reaching
    bug: "ice" is a substring of "officer", "war" of "warning"/"warrior",
    "sand" of "thousand", "city" of "capacity"/"velocity", "cell" of
    "excellent" - all common words in historical narration, silently
    misrouting scenes to the wrong setting/subject/outfit.

    Allows an optional trailing "s"/"es" so a singular keyword still matches
    its plural - a real published title ("...Octopuses Have 3 Hearts...")
    wouldn't match keyword "octopus" without this, since \\b requires a
    boundary immediately after "octopus" and "octopuses" has none there."""
    if " " in keyword or "-" in keyword:
        return keyword in haystack
    return re.search(rf"\b{re.escape(keyword)}(?:es|s)?\b", haystack) is not None


def _count_keyword(haystack: str, keyword: str) -> int:
    if " " in keyword or "-" in keyword:
        return haystack.count(keyword)
    return len(re.findall(rf"\b{re.escape(keyword)}\b", haystack))


# --- environment settings (ground + background elements) -------------------

_KEYWORD_TO_SETTING = [
    (("snow", "siberia", "arctic", "ice", "frozen", "winter", "cold", "blizzard"), "snow"),
    # Checked before the general "water" bucket below - dock/pier vocabulary
    # used to fall into "harbor" being one of water's own keywords, which
    # meant a scene about a departure or a missing ship rendered as bare
    # open water with a wave line, indistinguishable from every other ocean
    # scene. A pier + docked ship is a visually distinct silhouette.
    (("harbor", "dock", "pier", "wharf", "quay", "moored", "anchored", "dockside", "seaport", "dockyard"), "harbor"),
    (("ocean", "sea", "beach", "coast", "island", "ship", "boat", "wave", "submarine",
      "navy", "naval", "destroyer", "warship", "periscope", "fleet",
      "octopus", "squid", "cephalopod", "marine", "underwater", "aquatic",
      "deep-sea", "deep sea", "tentacle", "reef", "fish", "whale", "shark"), "water"),
    (("mountain", "valley", "cliff", "peak", "himalay", "andes", "alps"), "mountain"),
    (("war", "battle", "combat", "trench", "front line", "rubble", "bomb",
      "wreckage", "crash", "invasion", "siege"), "ruins"),
    (("forest", "jungle", "wood", "tree", "wilderness", "mistletoe", "branch", "oak", "grove"), "forest"),
    (("desert", "sand", "sahara", "dune"), "desert"),
    # Checked before "palace"'s "court" keyword and before generic "indoor" -
    # a trial is technically indoors but a witness stand/jury box reads as a
    # completely different scene from an office or a throne room.
    (("trial", "tribunal", "courtroom", "jury", "verdict", "testify", "testified",
      "prosecut", "defendant", "stood accused", "on trial", "witness stand"), "courtroom"),
    # Checked before generic "indoor" - "cell" used to route a prison scene
    # into the same office/lab/factory bucket as everything else indoors.
    (("dungeon", "prison", "imprisoned", "captive", "shackled", "incarcerated",
      "cell", "cellar", "chained", "chains", "jail", "jailed"), "dungeon"),
    (("room", "office", "lab", "laboratory", "indoor", "house", "factory", "bunker"), "indoor"),
    (("palace", "throne", "castle", "fortress", "court", "coronation", "monarchy"), "palace"),
    (("temple", "pyramid", "tomb", "pharaoh", "sphinx", "ziggurat", "acropolis",
      "parthenon", "ancient egypt", "mesopotamia", "ruins of"), "ancient"),
    # Checked before generic "city" - assassination/political-plot scenes
    # used to have no keyword bucket of their own and fell through to
    # "default" (a plain house+tree exterior) despite being a large share of
    # modern_history/dark_history content.
    (("assassinat", "coup", "conspiracy", "conspired", "plotted", "senate", "parliament",
      "minister", "president", "prime minister", "congress", "statesman", "chancellor",
      "regime", "politician", "capitol", "government building"), "government"),
    (("city", "street", "capital", "town square", "market", "urban", "metropolis"), "city"),
    (("olympus", "zeus", "poseidon", "hades", "underworld", "the gods", "god of",
      "goddess of", "pantheon", "valhalla", "asgard", "mythology", "mythical"), "mythic"),
]

# Settings so generic/common that a video otherwise repeats the same
# rendered look scene after scene with no narrative reason - see
# _resolve_setting. Weather/terrain settings (snow, desert, forest, water,
# harbor, mountain, mythic, ancient) are deliberately excluded: those really
# do repeat legitimately across a genuinely single-setting narrative (a whole
# scene sequence set in a desert, a whole video about an ancient temple), so
# forcing variety there would fight the actual story instead of fixing a bug.
_OVERLOAD_SETTINGS = {"default", "indoor", "city", "palace", "government"}
_OVERLOAD_ROTATION = ["city", "government", "palace", "indoor", "default"]

GROUND_COLORS = {
    "snow": (238, 242, 245),
    "water": (150, 190, 210),
    "harbor": (150, 158, 165),
    "mountain": (200, 200, 190),
    "ruins": (190, 180, 165),
    "forest": (160, 195, 140),
    "desert": (225, 200, 150),
    "indoor": (210, 190, 160),
    "dungeon": (95, 92, 88),
    "courtroom": (168, 138, 96),
    "palace": (222, 210, 188),
    "ancient": (218, 198, 160),
    "city": (188, 192, 198),
    "government": (206, 204, 196),
    "mythic": (232, 222, 196),
    "default": (200, 210, 190),
}


def _setting_for_scene(scene: Scene) -> str:
    haystack = f"{scene.narration} {' '.join(scene.visual_keywords)}".lower()
    for keywords, setting in _KEYWORD_TO_SETTING:
        if any(_contains_keyword(haystack, kw) for kw in keywords):
            return setting
    return "default"


def _resolve_setting(scene: Scene, prev_setting: Optional[str], rng: random.Random) -> str:
    """Same as _setting_for_scene, but breaks up back-to-back repeats of the
    generic/overloaded settings (see _OVERLOAD_SETTINGS) that otherwise make
    consecutive scenes - and consecutive videos - render near-identical
    backgrounds. A real, specific match (e.g. "desert") is never overridden,
    even if repeated many scenes in a row - only the generic buckets are."""
    setting = _setting_for_scene(scene)
    if setting in _OVERLOAD_SETTINGS and setting == prev_setting:
        choices = [s for s in _OVERLOAD_ROTATION if s != setting]
        return rng.choice(choices)
    return setting


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


def _draw_dock(draw: ImageDraw.ImageDraw, rng: random.Random, cx: float, base_y: float, scale: float) -> None:
    """A wooden pier walkway extending toward the viewer, with a couple of
    mooring posts - the thing that makes "harbor" read as a departure point,
    not just another patch of open water."""
    w, h = 420 * scale, 40 * scale
    deck = [(cx - w / 2, base_y - h), (cx + w / 2, base_y - h), (cx + w * 0.7, base_y), (cx - w * 0.7, base_y)]
    _sketchy_polyline(draw, rng, deck, fill=(120, 90, 60), close=True, width=int(5 * scale) or 3)
    for i in range(5):
        px = cx - w * 0.6 + (w * 1.2) * i / 4
        plank = [(px, base_y - h), (px, base_y)]
        _sketchy_polyline(draw, rng, plank, width=max(2, int(3 * scale)))
    for side in (-1, 1):
        post_x = cx + side * w * 0.42
        post = [(post_x, base_y - h - 55 * scale), (post_x, base_y - h * 0.3)]
        _sketchy_polyline(draw, rng, post, width=int(10 * scale) or 4)


def _draw_ship(draw: ImageDraw.ImageDraw, rng: random.Random, cx: float, base_y: float, scale: float) -> None:
    """A simple docked-ship silhouette: curved hull, one mast, one sail -
    distinct enough from the pier itself that a harbor scene reads as
    "a ship at dock", not just an empty walkway."""
    hull_w, hull_h = 300 * scale, 90 * scale
    hull = [(cx - hull_w / 2, base_y - hull_h), (cx + hull_w / 2, base_y - hull_h),
            (cx + hull_w * 0.38, base_y), (cx - hull_w * 0.38, base_y)]
    _sketchy_polyline(draw, rng, hull, fill=(70, 70, 75), close=True, width=int(6 * scale) or 3)
    mast = [(cx, base_y - hull_h), (cx, base_y - hull_h - 220 * scale)]
    _sketchy_polyline(draw, rng, mast, width=int(6 * scale) or 3)
    sail = [(cx, base_y - hull_h - 200 * scale), (cx, base_y - hull_h - 40 * scale),
            (cx + 110 * scale, base_y - hull_h - 60 * scale)]
    _sketchy_polyline(draw, rng, sail, fill=(235, 232, 222), close=True, width=int(4 * scale) or 3)


def _draw_capitol(draw: ImageDraw.ImageDraw, rng: random.Random, cx: float, base_y: float, scale: float) -> None:
    """A columned government building topped with a rounded dome - same
    column construction as _draw_temple, but a dome (not a triangular
    pediment) is what makes it read as "seat of power" rather than "ancient
    ruin", so assassination/political-plot scenes get their own silhouette
    instead of reusing the temple look."""
    w, h = 400 * scale, 210 * scale
    col_w = w / 6
    for i in range(6):
        cx_i = cx - w / 2 + col_w * i + col_w / 2
        col = [(cx_i - col_w * 0.26, base_y), (cx_i - col_w * 0.26, base_y - h),
               (cx_i + col_w * 0.26, base_y - h), (cx_i + col_w * 0.26, base_y)]
        _sketchy_polyline(draw, rng, col, fill=(215, 210, 195), width=int(4 * scale) or 3)
    deck = [(cx - w / 2, base_y - h), (cx + w / 2, base_y - h), (cx + w / 2, base_y - h * 1.06), (cx - w / 2, base_y - h * 1.06)]
    _sketchy_polyline(draw, rng, deck, fill=(195, 188, 172), close=True, width=int(5 * scale) or 3)
    dome_r = w * 0.22
    draw.pieslice([cx - dome_r, base_y - h * 1.06 - dome_r * 1.6, cx + dome_r, base_y - h * 1.06 + dome_r * 0.4],
                  180, 360, fill=(180, 172, 155), outline=INK, width=int(5 * scale) or 3)
    draw.line([(cx, base_y - h * 1.06 - dome_r * 1.6), (cx, base_y - h * 1.06 - dome_r * 2.0)], fill=INK, width=int(4 * scale) or 3)


_ELEMENT_DRAWERS = {
    # "indoor"/"dungeon"/"courtroom" are handled separately by
    # _draw_indoor_scene - a real interior (wall/floor/window/furniture), not
    # this exterior-props dict, since a house prop standing on grass under an
    # open sky (what this used to map to) reads as outside no matter what
    # the setting is named.
    "snow": [_draw_house, _draw_tree],
    "mountain": [_draw_mountain, _draw_tree],
    "ruins": [_draw_ruin],
    "forest": [_draw_tree, _draw_tree, _draw_house],
    "desert": [_draw_ruin],
    "water": [_draw_wave],
    "harbor": [_draw_dock, _draw_ship],
    "palace": [_draw_castle],
    "ancient": [_draw_temple],
    "city": [_draw_city_building, _draw_city_building],
    "government": [_draw_capitol],
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

# --- Historical / Mythological Character Archetypes --------------------------
# Each archetype defines: (outfit_rgb, headwear, weapon, default_pose, description)
# Used to render the actual historical/mythological figure (Odysseus, knight, etc.)
# instead of a generic narrator.
_CHARACTER_ARCHETYPES = {
    # Greek / Mythological
    "odysseus":     ((85, 60, 40), "helmet", "spear", "raised", "Greek hero, worn armor"),
    "iliad":        ((85, 60, 40), "helmet", "spear", "raised", "Greek hero, worn armor"),
    "trojan":       ((85, 60, 40), "helmet", "spear", "raised", "Greek hero, worn armor"),
    "achilles":     ((180, 160, 120), "helmet", "spear", "raised", "Golden armor, pride"),
    "hercules":     ((100, 60, 40), None, "club", "crossed", "Lion skin, brute strength"),
    "perseus":      ((90, 70, 50), "cap", "sword", "raised", "Winged sandals, harpe"),
    "theseus":      ((85, 60, 40), None, "sword", "raised", "Athenian hero"),
    "jason":        ((80, 100, 120), "cap", "spear", "sides", "Argonaut leader"),
    # Medieval / Knight
    "knight":       ((180, 180, 190), "helmet", "sword", "crossed", "Plate armor, shield"),
    "crusader":     ((200, 180, 160), "helmet", "sword", "crossed", "White surcoat, cross"),
    "templar":      ((200, 180, 160), "helmet", "sword", "crossed", "White mantle, red cross"),
    "samurai":      ((60, 40, 30), "helmet", "katana", "raised", "Ō-yoroi, katana"),
    "ronin":        ((80, 60, 40), "hat", "katana", "sides", "Worn armor, wandering"),
    # Roman
    "roman":        ((100, 80, 60), "helmet", "gladius", "crossed", "Lorica segmentata"),
    "centurion":    ((120, 90, 60), "helmet", "vine_staff", "raised", "Transverse crest"),
    "caesar":       ((160, 140, 100), "crown", "sword", "raised", "Laurel wreath, toga"),
    "gladiator":    ((150, 100, 50), "helmet", "trident", "fighting", "Minimal armor, net"),
    # Viking / Norse
    "viking":       ((100, 80, 60), "helmet", "axe", "raised", "Chainmail, round shield"),
    "norse":        ((100, 80, 60), "helmet", "axe", "raised", "Chainmail, round shield"),
    "odin":         ((80, 60, 40), "hat", "spear", "sides", "One eye, ravens"),
    "thor":         ((160, 140, 100), None, "hammer", "raised", "Mjolnir, belt of strength"),
    # Egyptian
    "egyptian":     ((200, 180, 120), "crown", "khopesh", "crossed", "Linen kilt, gold"),
    "pharaoh":      ((255, 215, 0), "crown", "crook_flail", "crossed", "Double crown, regalia"),
    "anubis":       ((40, 40, 40), "crown", "staff", "sides", "Jackal head, black"),
    # Aztec / Maya
    "aztec":        ((180, 120, 40), "crown", "macuahuitl", "fighting", "Feathered headdress"),
    "maya":         ((160, 140, 80), "crown", "obsidian_sword", "fighting", "Jade, quetzal feathers"),
    # Other
    "pirate":       ((60, 40, 30), "hat", "cutlass", "raised", "Coat, eye patch"),
    "explorer":     ((120, 100, 80), "hat", "compass", "raised", "Map, weathered"),
    "scholar":      ((80, 70, 60), "cap", "scroll", "sides", "Robes, quill"),
    "priest":       ((220, 220, 220), None, "staff", "sides", "White robes"),
    "assassin":     ((30, 30, 30), "cap", "dagger", "fighting", "Hood, dark leather"),
    "general":      ((80, 60, 40), "helmet", "sword", "raised", "Commander's cloak"),
}

# Keyword mapping: scene narration/visual_keywords → archetype
_ARCHETYPE_KEYWORDS = [
    (("odysseus", "ulysses", "iliad", "trojan", "trojan war", "homer"), "odysseus"),
    (("achilles", "myrmidon"), "achilles"),
    (("hercules", "herakles"), "hercules"),
    (("perseus", "medusa", "gorgon"), "perseus"),
    (("theseus", "minotaur", "labyrinth"), "theseus"),
    (("jason", "argonaut", "golden fleece"), "jason"),
    (("knight", "knights", "chivalry", "round table", "arthur", "merlin", "excalibur", "camelot"), "knight"),
    (("crusader", "crusade", "holy land", "jerusalem"), "crusader"),
    (("templar", "templars", "temple"), "templar"),
    (("samurai", "shogun", "bushido", "daimyo", "katana", "ronin"), "samurai"),
    (("ronin", "masterless"), "ronin"),
    (("centurion", "optio"), "centurion"),
    (("roman", "legion", "legionary", "caesar", "pompey", "cicero", "spqr"), "roman"),
    (("caesar", "julius", "augustus"), "caesar"),
    (("roman", "legion", "legionary", "spqr"), "roman"),
    (("gladiator", "colosseum", "arena"), "gladiator"),
    (("viking", "vikings", "norseman", "valhalla", "raids"), "viking"),
    (("odin", "thor", "loki", "freya", "valhalla", "asgard", "midgard"), "odin"),
    (("thor", "mjolnir", "hammer"), "thor"),
    (("egyptian", "pharaoh", "pyramid", "hieroglyph", "nile", "anubis", "ra", "osiris"), "egyptian"),
    (("pharaoh", "tutankhamun", "ramses", "cleopatra"), "pharaoh"),
    (("anubis", "jackal"), "anubis"),
    (("aztec", "tenochtitlan", "quetzalcoatl", "human sacrifice"), "aztec"),
    (("maya", "mayan", "chichen itza"), "maya"),
    (("pirate", "buccaneer", "privateer", "blackbeard", "caribbean"), "pirate"),
    (("explorer", "columbus", "magellan", "voyage", "new world"), "explorer"),
    (("assassin", "hashashin", "hidden blade"), "assassin"),
    (("general", "commander", "marshal", "strategy"), "general"),
]


def _resolve_character_archetype(scene: Scene) -> str:
    """Map scene narration/keywords to a character archetype."""
    haystack = _scene_haystack(scene)
    for keywords, archetype in _ARCHETYPE_KEYWORDS:
        if any(_contains_keyword(haystack, kw) for kw in keywords):
            return archetype
    return "scholar"  # default: generic narrator


# Two-person melee - distinct from large-scale "battle" (which stays a single
# character in a war-torn setting): a personal fight/duel/brawl gets two
# characters actually swinging at each other, see _compose_fight_scene.
_FIGHT_KEYWORDS = ("fight", "fought", "duel", "brawl", "melee", "wrestl", "punch", "sparr",
                    "sword fight", "swordfight", "clashed swords", "clash", "grapple")

# A scene set among a crowd of onlookers - court, market, gathering - gets a
# handful of small background figures instead of the lone focal character,
# see _CROWD_COLORS / _draw_background_person.
_CROWD_KEYWORDS = ("court", "courtiers", "crowd", "chatter", "gathered", "gathering",
                    "marketplace", "town square", "audience", "onlookers", "spectators",
                    "townsfolk", "villagers", "murmur", "assembly", "council",
                    "family", "crew", "followers", "companions", "soldiers", "guards",
                    "citizens", "worshippers", "pilgrims", "colleagues", "delegation")


def _scene_haystack(scene: Scene) -> str:
    return f"{scene.narration} {' '.join(scene.visual_keywords)}".lower()


def _is_fight_scene(scene: Scene) -> bool:
    haystack = _scene_haystack(scene)
    return any(_contains_keyword(haystack, kw) for kw in _FIGHT_KEYWORDS)


def _is_crowd_scene(scene: Scene) -> bool:
    haystack = _scene_haystack(scene)
    return any(_contains_keyword(haystack, kw) for kw in _CROWD_KEYWORDS)


def _frame_base_scale(w: int, h: int) -> float:
    """The single scale factor every element drawer (character, house,
    tree, ...) multiplies its own geometry by. Deliberately keyed off the
    SHORTER side, not just h - see _compose_scene's call site for the bug
    this fixes (h alone made shorts/portrait render ~78% oversized, since
    width - the actual constraint in a narrower frame - was never part of
    the calculation)."""
    return min(w, h) / 1080


def _match(scene: Scene, table) -> Optional[str]:
    haystack = _scene_haystack(scene)
    for keywords, value in table:
        if any(_contains_keyword(haystack, kw) for kw in keywords):
            return value
    return None


# --- Battle Scene Helpers ----------------------------------------------------
# Expanded fight keywords
_FIGHT_KEYWORDS = ("fight", "fought", "duel", "brawl", "melee", "wrestl", "punch", "sparr",
                    "sword fight", "swordfight", "clashed swords", "clash", "grapple",
                    "battle", "war", "combat", "siege", "assault", "skirmish", "engagement")

# Large-scale battle keywords (armies vs personal fights)
_BATTLE_KEYWORDS = ("army", "battalion", "regiment", "division", "legion", "horde",
                    "thousand", "ten thousand", "hundred thousand", "host", "force",
                    "battle", "war", "combat", "siege", "assault", "skirmish", "engagement")


def _is_battle_scene(scene: Scene) -> bool:
    """True for large-scale battles (armies) vs personal fights."""
    haystack = _scene_haystack(scene)
    return any(_contains_keyword(haystack, kw) for kw in _BATTLE_KEYWORDS)


def _is_battle_scene_public(scene: Scene) -> bool:
    """Public wrapper for _is_battle_scene for testing."""
    return _is_battle_scene(scene)


def _draw_soldier(draw: ImageDraw.ImageDraw, rng: random.Random, cx: float, ground_y: float,
                  scale: float, outfit: tuple, phase: float, facing: int = 1,
                  pose: str = "standing", weapon: str = "spear") -> None:
    """Simplified soldier figure for background — less detail than main character."""
    head_r = 25 * scale
    hip_y = ground_y - 55 * scale
    shoulder_y = hip_y - 65 * scale
    head_cy = shoulder_y - head_r * 1.15
    
    leg_swing = math.sin(phase) * 6 * scale
    arm_swing = math.sin(phase + math.pi) * 4 * scale
    
    # Legs
    draw.line([(cx - 14 * scale, hip_y), (cx - 16 * scale + leg_swing, ground_y)], 
              fill=INK, width=max(3, round(8 * scale)))
    draw.line([(cx + 14 * scale, hip_y), (cx + 16 * scale - leg_swing, ground_y)], 
              fill=INK, width=max(3, round(8 * scale)))
    
    # Torso
    torso = [(cx - 22 * scale, shoulder_y), (cx + 22 * scale, shoulder_y),
             (cx + 17 * scale, hip_y), (cx - 17 * scale, hip_y)]
    _sketchy_polyline(draw, rng, torso, fill=outfit, close=True, width=max(2, round(4 * scale)))
    
    # Arms based on pose
    if pose == "aiming":
        draw.line([(cx - 22 * scale, shoulder_y), (cx - 45 * scale, shoulder_y - 25 * scale)], 
                  fill=INK, width=max(2, round(6 * scale)))
        draw.line([(cx + 22 * scale, shoulder_y), (cx + 10 * scale, shoulder_y + 15 * scale)], 
                  fill=INK, width=max(2, round(6 * scale)))
        _draw_weapon(draw, rng, cx, shoulder_y, scale, "crossbow", facing)
    elif pose == "charging":
        draw.line([(cx - 22 * scale, shoulder_y), (cx - 45 * scale + arm_swing, hip_y)], 
                  fill=INK, width=max(2, round(6 * scale)))
        draw.line([(cx + 22 * scale, shoulder_y), (cx + 30 * scale - arm_swing, shoulder_y)], 
                  fill=INK, width=max(2, round(6 * scale)))
        _draw_weapon(draw, rng, cx, shoulder_y, scale, weapon, facing)
    else:  # standing/guarding
        draw.line([(cx - 22 * scale, shoulder_y), (cx - 30 * scale, hip_y - 10 * scale)], 
                  fill=INK, width=max(2, round(6 * scale)))
        draw.line([(cx + 22 * scale, shoulder_y), (cx + 30 * scale, hip_y - 10 * scale)], 
                  fill=INK, width=max(2, round(6 * scale)))
        _draw_weapon(draw, rng, cx, shoulder_y, scale, weapon, facing)
    
    # Head with scared expression
    skin = (235, 205, 175)
    draw.ellipse([cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r], 
                 fill=skin, outline=INK, width=max(2, round(3 * scale)))
    
    # Wide eyes (fear)
    eye_r = head_r * 0.18
    for ex in (cx - head_r * 0.35, cx + head_r * 0.35):
        draw.ellipse([ex - eye_r, head_cy - eye_r, ex + eye_r, head_cy + eye_r],
                     fill=(255, 255, 255), outline=INK, width=2)
        draw.ellipse([ex - eye_r * 0.6, head_cy - eye_r * 0.6, 
                      ex + eye_r * 0.6, head_cy + eye_r * 0.6], fill=INK)
    
    # Raised eyebrows (fear)
    brow_w = max(2, round(head_r * 0.05))
    for ex in (cx - head_r * 0.35, cx + head_r * 0.35):
        draw.arc([ex - head_r * 0.2, head_cy - head_r * 0.5, 
                  ex + head_r * 0.2, head_cy - head_r * 0.1],
                 start=200, end=340, fill=INK, width=brow_w)
    
    # Helmet (most soldiers)
    if rng.random() < 0.8:
        _helmet(draw, cx, head_cy, head_r)


def _match(scene: Scene, table) -> Optional[str]:
    haystack = _scene_haystack(scene)
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


def draw_character(draw: ImageDraw.ImageDraw, rng: random.Random, cx: float, ground_y: float, scale: float, outfit: tuple, headwear: Optional[str], mood: str, pose: str = "sides", phase: float = 0.0, facing: int = 1, weapon: Optional[str] = None) -> None:
    head_r = 95 * scale
    hip_y = ground_y - 210 * scale
    shoulder_y = hip_y - 225 * scale
    head_cy = shoulder_y - head_r * 1.15

    # Idle weight-shift sway, driven by phase (one full cycle per loop):
    # legs swing gently opposite each other and arms swing opposite the
    # legs, like a person shifting weight in place rather than a frozen
    # mannequin - the sprite-frame loop in generate_scene_clip renders this
    # across a handful of phases so the character actually moves.
    # Amplitudes roughly doubled from the original 14/10px - at the original
    # size, combined with HUMAN_SCALE's 0.5 reduction, the idle sway was only
    # a few pixels on screen and read as "barely moving" (a reported
    # complaint against real output), not as a character actually shifting
    # weight.
    leg_swing = math.sin(phase) * 26 * scale
    arm_swing = math.sin(phase + math.pi) * 20 * scale

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
    elif pose == "fighting":
        # One arm (the side facing the opponent, per `facing`) throws a
        # punch that extends toward them as phase sweeps 0..pi, then
        # withdraws; the other arm stays back in a guard near the chest.
        # Two fighters share this same code with opposite `facing` and a
        # phase offset (see _compose_fight_scene), so they alternate
        # throwing punches at each other rather than mirroring in sync.
        punch = max(0.0, math.sin(phase))
        front_shoulder_x = cx + 80 * scale * facing
        front_fist = (cx + facing * (60 + 155 * punch) * scale, shoulder_y - 10 * scale)
        _sketchy_polyline(draw, rng, [(front_shoulder_x, shoulder_y), front_fist], width=int(18 * scale) or 4)
        rear_shoulder_x = cx - 80 * scale * facing
        rear_fist = (cx - facing * 45 * scale, shoulder_y + 45 * scale)
        _sketchy_polyline(draw, rng, [(rear_shoulder_x, shoulder_y), rear_fist], width=int(18 * scale) or 4)
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
    
    # Draw weapon in hand if specified and pose supports it
    if weapon and pose in ("raised", "fighting", "crossed"):
        _draw_weapon(draw, rng, cx, head_cy - 100 * scale, scale, weapon, facing)


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
    "harbor": _texture_concrete,   # doubles as plank lines
    "government": _texture_concrete,
    "default": _texture_grass,
}


# --- fight scenes: two characters trading swings, plus an impact spark -----

def _draw_impact_burst(draw: ImageDraw.ImageDraw, cx: float, cy: float, scale: float) -> None:
    """A jagged starburst flashed at the collision point on a punch's peak
    extension - the classic comic-panel "POW" shape, cheap to draw and reads
    instantly as impact even as a single still frame."""
    color = (255, 205, 60)
    pts = []
    for i in range(12):
        ang = i * math.pi / 6
        r = (60 if i % 2 == 0 else 24) * scale
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    draw.polygon(pts, fill=color, outline=INK, width=max(3, round(4 * scale)))


def _draw_weapon(draw: ImageDraw.ImageDraw, rng: random.Random, cx: float, cy: float,
                 scale: float, weapon: str, facing: int = 1) -> None:
    """Draw weapon in character's hand based on archetype."""
    lw = max(2, round(4 * scale))
    hand_x = cx + facing * 85 * scale
    hand_y = cy + 40 * scale  # approximate hand position
    
    if weapon == "spear":
        pts = [(hand_x, hand_y), (hand_x + facing * 200 * scale, hand_y - 60 * scale)]
        draw.line(pts, fill=(150, 130, 90), width=lw, joint="curve")
        tip = pts[1]
        draw.polygon([
            (tip[0] - facing * 10 * scale, tip[1] - 8 * scale),
            (tip[0] + facing * 6 * scale, tip[1]),
            (tip[0] - facing * 10 * scale, tip[1] + 8 * scale),
        ], fill=(180, 180, 180), outline=INK, width=max(1, lw))
    
    elif weapon == "sword":
        pts = [(hand_x, hand_y), (hand_x + facing * 140 * scale, hand_y - 20 * scale)]
        draw.line(pts, fill=(180, 180, 180), width=lw + 2, joint="curve")
        draw.line([
            (hand_x + facing * 20 * scale, hand_y + 10 * scale),
            (hand_x + facing * 20 * scale, hand_y - 10 * scale),
        ], fill=(100, 80, 50), width=max(2, lw))
        draw.ellipse([hand_x - 8 * scale, hand_y - 8 * scale,
                      hand_x + 8 * scale, hand_y + 8 * scale], fill=(100, 80, 50))
    
    elif weapon == "katana":
        pts = [(hand_x, hand_y), (hand_x + facing * 160 * scale, hand_y - 10 * scale)]
        draw.line(pts, fill=(200, 200, 200), width=lw, joint="curve")
        draw.rectangle([
            hand_x + facing * 18 * scale - 15 * scale, hand_y - 8 * scale,
            hand_x + facing * 18 * scale + 15 * scale, hand_y + 8 * scale
        ], fill=(100, 80, 50), outline=INK, width=2)
    
    elif weapon == "axe":
        pts = [(hand_x, hand_y), (hand_x + facing * 100 * scale, hand_y - 30 * scale)]
        draw.line(pts, fill=(80, 60, 40), width=lw + 4, joint="curve")
        draw.polygon([
            (hand_x + facing * 90 * scale, hand_y - 50 * scale),
            (hand_x + facing * 110 * scale, hand_y - 20 * scale),
            (hand_x + facing * 110 * scale, hand_y + 10 * scale),
            (hand_x + facing * 90 * scale, hand_y - 20 * scale),
        ], fill=(140, 140, 140), outline=INK, width=max(2, lw))
    
    elif weapon == "club":
        pts = [(hand_x, hand_y), (hand_x + facing * 80 * scale, hand_y + 20 * scale)]
        draw.line(pts, fill=(100, 70, 50), width=lw + 8, joint="curve")
        draw.ellipse([hand_x + facing * 70 * scale - 15, hand_y + 5,
                      hand_x + facing * 70 * scale + 15, hand_y + 35], fill=(80, 50, 30))
    
    elif weapon == "trident":
        center = (hand_x + facing * 120 * scale, hand_y - 10 * scale)
        for i in range(3):
            offset = (i - 1) * 15 * scale
            pts = [(hand_x, hand_y), (center[0] + offset, center[1] - 30 * scale)]
            draw.line(pts, fill=(180, 180, 180), width=lw)
    
    elif weapon == "khopesh":
        pts = [(hand_x, hand_y)]
        for t in range(0, 101, 10):
            curve = math.sin(t * math.pi / 100) * 80 * scale
            x = hand_x + facing * t * 1.2 * scale
            y = hand_y - curve
            pts.append((x, y))
        draw.line(pts, fill=(200, 170, 60), width=lw + 2, joint="curve")
    
    elif weapon == "macuahuitl":
        pts = [(hand_x, hand_y), (hand_x + facing * 100 * scale, hand_y + 10 * scale)]
        draw.line(pts, fill=(40, 40, 40), width=lw + 12, joint="curve")
        for i in range(6):
            x = hand_x + facing * (20 + i * 12) * scale
            draw.rectangle([x - 3, hand_y - 20 * scale - 5,
                           x + 3, hand_y - 20 * scale + 5], fill=(20, 20, 20))
    
    elif weapon in ("staff", "vine_staff", "spear"):
        pass
    
    elif weapon == "dagger":
        pts = [(hand_x, hand_y), (hand_x + facing * 50 * scale, hand_y - 5 * scale)]
        draw.line(pts, fill=(180, 180, 180), width=lw + 1, joint="curve")
    
    elif weapon in ("crook_flail", "staff"):
        pts = [(hand_x, hand_y), (hand_x + facing * 100 * scale, hand_y - 80 * scale)]
        draw.line(pts, fill=(220, 190, 120), width=lw + 2, joint="curve")
        draw.ellipse([hand_x + facing * 100 * scale - 15 * scale, hand_y - 100 * scale,
                      hand_x + facing * 100 * scale + 15 * scale, hand_y - 70 * scale],
                     outline=(220, 190, 120), width=lw)

    elif weapon == "crossbow":
        draw.rectangle([
            hand_x - 15 * scale, hand_y - 8 * scale,
            hand_x + 40 * scale, hand_y + 8 * scale
        ], fill=(80, 60, 40), outline=INK, width=2)
        draw.ellipse([hand_x + 25 * scale, hand_y - 25 * scale,
                      hand_x + 55 * scale, hand_y + 25 * scale],
                     outline=(80, 60, 40), width=3)

    elif weapon == "bow":
        pts = [(hand_x + facing * 5 * scale, hand_y - 60 * scale),
               (hand_x + facing * 5 * scale, hand_y + 60 * scale)]
        draw.line(pts, fill=(100, 80, 50), width=lw + 4, joint="curve")
        draw.line([(hand_x + facing * 5 * scale, hand_y - 60 * scale),
                   (hand_x + facing * 5 * scale, hand_y + 60 * scale)],
                  fill=(100, 100, 100), width=1)

    elif weapon == "hammer":
        pts = [(hand_x, hand_y), (hand_x + facing * 90 * scale, hand_y - 10 * scale)]
        draw.line(pts, fill=(80, 60, 40), width=lw + 6, joint="curve")
        draw.rectangle([
            hand_x + facing * 80 * scale, hand_y - 30 * scale,
            hand_x + facing * 110 * scale, hand_y + 10 * scale
        ], fill=(140, 140, 140), outline=INK, width=max(2, lw))

    elif weapon == "mace":
        pts = [(hand_x, hand_y), (hand_x + facing * 80 * scale, hand_y - 5 * scale)]
        draw.line(pts, fill=(80, 60, 40), width=lw + 4, joint="curve")
        draw.ellipse([
            hand_x + facing * 75 * scale - 18 * scale, hand_y - 23 * scale,
            hand_x + facing * 75 * scale + 18 * scale, hand_y + 13 * scale
        ], fill=(140, 140, 140), outline=INK, width=max(2, lw))
        for spike in range(4):
            ang = spike * math.pi / 2
            sx = hand_x + facing * 75 * scale + 22 * scale * math.cos(ang)
            sy = hand_y - 5 * scale + 22 * scale * math.sin(ang)
            draw.line([(hand_x + facing * 75 * scale, hand_y - 5 * scale), (sx, sy)],
                      fill=(140, 140, 140), width=max(1, round(2 * scale)))

    elif weapon in ("obsidian_sword", "macana"):
        pts = [(hand_x, hand_y), (hand_x + facing * 100 * scale, hand_y + 10 * scale)]
        draw.line(pts, fill=(20, 20, 20), width=lw + 12, joint="curve")
        for i in range(6):
            x = hand_x + facing * (20 + i * 12) * scale
            draw.rectangle([x - 3, hand_y - 20 * scale - 5,
                           x + 3, hand_y - 20 * scale + 5], fill=(20, 20, 20))
# character - for court/market/gathering scenes so "a crowd murmured" or
# "the court fell silent" doesn't render as one giant alone on an empty
# stage. Deliberately much simpler than draw_character (no outfit/headwear
# detail) so they read as background, not competing focal points. ----------

_CROWD_COLORS = [(150, 130, 190), (190, 150, 110), (110, 150, 150), (170, 110, 120), (140, 160, 110), (120, 130, 170)]


def _draw_background_person(draw: ImageDraw.ImageDraw, rng: random.Random, cx: float, ground_y: float, scale: float, color: tuple, phase: float, idx: int) -> None:
    # Each figure sways on its own phase offset (seeded by index) so a crowd
    # of them doesn't move in unison like one repeated stamp.
    sway = math.sin(phase * 0.8 + idx * 1.7) * 6 * scale
    head_r = 30 * scale
    hip_y = ground_y - 62 * scale
    shoulder_y = hip_y - 70 * scale
    head_cy = shoulder_y - head_r * 1.1
    leg_w = max(3, round(8 * scale))
    draw.line([(cx + sway, hip_y), (cx - 16 * scale + sway, ground_y)], fill=INK, width=leg_w)
    draw.line([(cx + sway, hip_y), (cx + 16 * scale + sway, ground_y)], fill=INK, width=leg_w)
    body = [(cx - 24 * scale + sway, shoulder_y), (cx + 24 * scale + sway, shoulder_y),
            (cx + 18 * scale + sway, hip_y), (cx - 18 * scale + sway, hip_y)]
    _outlined_blob(draw, body, color, max(3, round(5 * scale)))
    draw.ellipse([cx - head_r + sway, head_cy - head_r, cx + head_r + sway, head_cy + head_r],
                 fill=(235, 205, 175), outline=INK, width=max(3, round(4 * scale)))


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
    """A video genuinely about octopuses should show an octopus regularly,
    even in scenes whose narration happens not to say 'octopus' (e.g. a
    sentence about a protein) - that's what subject_fallback is for.

    But a video is not "about" a creature just because it's mentioned once,
    anywhere. This used to count raw keyword hits across the whole script's
    combined text, so a single incidental mention deep in one scene of a
    multi-character narrative video (e.g. Jörmungandr, the sea serpent,
    named once in a Norse mythology video that's mostly about Baldur, Loki,
    and Ragnarok - nothing to do with fish) was enough to make "fish" win
    and then get slapped onto half of every OTHER scene by _resolve_subject,
    including ones about a completely unrelated character. Real single-
    subject videos have the subject explicitly named in a real *fraction* of
    scenes, not one passing mention - so that's what's required now, rather
    than any hit count above zero."""
    title_lower = extra_text.lower()
    for keywords, subject in _KEYWORD_TO_SUBJECT:
        if any(_contains_keyword(title_lower, kw) for kw in keywords):
            return subject

    scene_hits: dict = {}
    for scene in scenes:
        matched = _subject_for_scene(scene)
        if matched:
            scene_hits[matched] = scene_hits.get(matched, 0) + 1
    if not scene_hits:
        return None
    subject, hits = max(scene_hits.items(), key=lambda kv: kv[1])
    if hits / len(scenes) < 0.3:
        return None
    return subject


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


# --- indoor scenes: a real interior, not a house prop standing outside -----

_WALL_COLORS = [(224, 210, 184), (210, 200, 188), (198, 206, 200), (216, 198, 176)]
_DUNGEON_WALL_COLORS = [(90, 86, 82), (82, 79, 76), (96, 92, 90)]
_COURTROOM_WALL_COLORS = [(124, 92, 62), (112, 84, 58), (130, 100, 70)]


def _draw_window(draw, rng, cx, cy, win_w, win_h, line_w, barred=False):
    draw.rectangle([cx - win_w / 2, cy - win_h / 2, cx + win_w / 2, cy + win_h / 2],
                    fill=(197, 224, 233), outline=INK, width=line_w)
    if barred:
        # Vertical bars instead of a plain sash cross - the one detail that
        # makes a small high window read as a cell, not just a dim office.
        bar_w = max(2, line_w - 1)
        for i in range(1, 4):
            bx = cx - win_w / 2 + win_w * i / 4
            draw.line([(bx, cy - win_h / 2), (bx, cy + win_h / 2)], fill=INK, width=bar_w)
    else:
        draw.line([(cx, cy - win_h / 2), (cx, cy + win_h / 2)], fill=INK, width=max(2, line_w - 1))
        draw.line([(cx - win_w / 2, cy), (cx + win_w / 2, cy)], fill=INK, width=max(2, line_w - 1))


def _draw_table(draw, rng, cx, floor_y, scale):
    top_w, top_h = 220 * scale, 26 * scale
    leg_h = 130 * scale
    lw = max(3, round(4 * scale))
    draw.rectangle([cx - top_w / 2, floor_y - leg_h - top_h, cx + top_w / 2, floor_y - leg_h],
                    fill=(150, 105, 70), outline=INK, width=lw)
    for lx in (cx - top_w / 2 + 16 * scale, cx + top_w / 2 - 16 * scale):
        draw.rectangle([lx - 9 * scale, floor_y - leg_h, lx + 9 * scale, floor_y],
                        fill=(120, 82, 55), outline=INK, width=max(2, round(3 * scale)))


def _draw_crate(draw, rng, cx, floor_y, scale):
    w_, h_ = 120 * scale, 120 * scale
    lw = max(3, round(4 * scale))
    draw.rectangle([cx - w_ / 2, floor_y - h_, cx + w_ / 2, floor_y], fill=(160, 120, 80), outline=INK, width=lw)
    draw.line([(cx - w_ / 2, floor_y - h_), (cx + w_ / 2, floor_y)], fill=INK, width=max(2, round(3 * scale)))
    draw.line([(cx + w_ / 2, floor_y - h_), (cx - w_ / 2, floor_y)], fill=INK, width=max(2, round(3 * scale)))


def _draw_bookshelf(draw, rng, cx, floor_y, scale):
    w_, h_ = 150 * scale, 300 * scale
    lw = max(3, round(4 * scale))
    draw.rectangle([cx - w_ / 2, floor_y - h_, cx + w_ / 2, floor_y], fill=(110, 78, 55), outline=INK, width=lw)
    shelves = 4
    for i in range(1, shelves):
        y = floor_y - h_ * i / shelves
        draw.line([(cx - w_ / 2, y), (cx + w_ / 2, y)], fill=INK, width=max(2, round(3 * scale)))
        for _ in range(rng.randint(2, 4)):
            bx = rng.uniform(cx - w_ / 2 + 8 * scale, cx + w_ / 2 - 20 * scale)
            bw = rng.uniform(10, 18) * scale
            bh = h_ / shelves - 14 * scale
            color = rng.choice([(180, 70, 70), (70, 100, 150), (200, 170, 70), (90, 130, 90)])
            draw.rectangle([bx, y - bh - 4 * scale, bx + bw, y - 4 * scale], fill=color, outline=INK, width=2)


def _draw_bench_platform(draw, rng, cx, floor_y, scale):
    """A raised judge's bench/dais with a step up to it - courtroom
    furniture, distinct from the table/crate/bookshelf props used for a
    plain office/lab so a trial doesn't render as an ordinary indoor scene."""
    w_, h_ = 260 * scale, 90 * scale
    lw = max(3, round(4 * scale))
    draw.rectangle([cx - w_ / 2, floor_y - h_, cx + w_ / 2, floor_y], fill=(90, 65, 45), outline=INK, width=lw)
    step_w, step_h = w_ * 1.15, 22 * scale
    draw.rectangle([cx - step_w / 2, floor_y - h_ - step_h, cx + step_w / 2, floor_y - h_],
                    fill=(105, 78, 55), outline=INK, width=lw)


_INTERIOR_VARIANTS = {
    "indoor": {"walls": _WALL_COLORS, "furniture": [_draw_table, _draw_crate, _draw_bookshelf], "barred": False},
    "dungeon": {"walls": _DUNGEON_WALL_COLORS, "furniture": [_draw_crate], "barred": True},
    "courtroom": {"walls": _COURTROOM_WALL_COLORS, "furniture": [_draw_bench_platform], "barred": False},
}


def _draw_indoor_scene(draw, rng, w, h, base_scale, variant: str = "indoor") -> int:
    """A real interior (wall, floor, window, a piece of furniture) instead of
    the old behaviour, where the "indoor" setting just drew a house sitting
    on grass under an open sky - a house prop is still an EXTERIOR shot no
    matter what the setting is called, which is exactly why every scene used
    to read as outside. Returns floor_y so the caller grounds the character
    on the same line.

    `variant` picks wall palette/furniture/window style so "indoor" (office/
    lab), "dungeon" (prison cell) and "courtroom" (trial) - all technically
    interiors - don't render as the same beige room; see _INTERIOR_VARIANTS."""
    spec = _INTERIOR_VARIANTS.get(variant, _INTERIOR_VARIANTS["indoor"])
    floor_y = round(h * 0.82)
    draw.rectangle([0, 0, w, floor_y], fill=rng.choice(spec["walls"]))
    draw.rectangle([0, floor_y, w, h], fill=GROUND_COLORS.get(variant, GROUND_COLORS["indoor"]))
    draw.line([(0, floor_y), (w, floor_y)], fill=INK, width=3)
    draw.rectangle([0, floor_y - round(10 * base_scale), w, floor_y], fill=(180, 165, 140))
    for i in range(1, 4):
        y = floor_y + (h - floor_y) * i / 4
        draw.line([(0, y), (w, y)], fill=(150, 138, 118), width=2)

    win_w, win_h = 210 * base_scale, 260 * base_scale
    win_cx = w * rng.uniform(0.12, 0.22)
    win_cy = floor_y * rng.uniform(0.30, 0.42)
    _draw_window(draw, rng, win_cx, win_cy, win_w, win_h, max(3, round(6 * base_scale)), barred=spec["barred"])

    furniture = rng.choice(spec["furniture"])
    furniture(draw, rng, w * rng.uniform(0.74, 0.88), floor_y, base_scale * rng.uniform(0.9, 1.2))
    return floor_y


# --- Dynamic Background Drawing Functions ------------------------------------
# These add variety to backgrounds based on scene type/content

_SKY_TINTS = [
    (255, 244, 224),  # warm dawn
    (226, 240, 250),  # cool morning blue
    (255, 235, 235),  # soft blush dusk
    (235, 245, 235),  # pale overcast mint
    (245, 240, 255),  # pale lavender
]


def _draw_sky_gradient(draw: ImageDraw.ImageDraw, rng: random.Random, w: int, sky_h: int, tint=None) -> None:
    """Soft vertical gradient from a gentle tint at the very top down to
    white just above the ground - subtle by design (this should read as
    atmosphere, not a sunset), picked per-scene so consecutive scenes don't
    all get the exact same cast."""
    if sky_h <= 0:
        return
    top_tint = tint or rng.choice(_SKY_TINTS)
    bands = max(1, min(28, sky_h // 24))
    band_h = sky_h / bands
    for i in range(bands):
        t = i / max(1, bands - 1)
        color = tuple(round(top_tint[c] + (255 - top_tint[c]) * t) for c in range(3))
        y0 = round(i * band_h)
        y1 = sky_h if i == bands - 1 else round((i + 1) * band_h)
        draw.rectangle([0, y0, w, y1], fill=color)


def _draw_horizon_hills(draw: ImageDraw.ImageDraw, rng: random.Random, w: int, ground_y: int, ground_color: tuple) -> None:
    """A soft, low rolling silhouette sitting just above the ground line - a
    cheap mid-depth layer so the sky-to-ground transition isn't one hard
    edge with nothing between it and the clouds. Muted/lightened toward the
    sky's white so it reads as distant, and left without a heavy ink
    outline (unlike every foreground element) so it stays recessive rather
    than competing with the actual scene content."""
    hill_h = ground_y * rng.uniform(0.05, 0.10)
    if hill_h < 4:
        return
    color = _lighten(ground_color, 0.45)
    n = 5
    pts = [(0, ground_y)]
    for i in range(n + 1):
        x = w * i / n
        y = ground_y - hill_h * rng.uniform(0.35, 1.0)
        pts.append((x, y))
    pts.append((w, ground_y))
    draw.polygon(pts, fill=color, outline=_lighten(ground_color, 0.2))


def _draw_smoke_plume(draw, rng, cx, cy, scale):
    color = rng.choice([(100, 100, 105), (120, 115, 115), (80, 80, 85)])
    pts = [(cx, cy)]
    for i in range(1, 6):
        sway = math.sin(i * 1.2) * 40 * scale
        pts.append((cx + sway, cy - i * 35 * scale))
    draw.line(pts, fill=color, width=int(30 * scale), joint="curve")


def _draw_crater(draw, rng, cx, ground_y, scale):
    w = rng.uniform(20, 60) * scale
    h = rng.uniform(5, 15) * scale
    pts = [(cx - w/2, ground_y), (cx - w*0.3, ground_y - h),
           (cx + w*0.1, ground_y - h*1.2), (cx + w*0.2, ground_y - h*0.5),
           (cx + w/2, ground_y)]
    _outlined_blob(draw, pts, (120, 120, 130), int(3 * scale))


def _draw_distant_fire(draw, rng, cx, ground_y, scale):
    h = rng.uniform(40, 80) * scale
    color = rng.choice([(255, 100, 30), (255, 140, 20), (255, 60, 20)])
    for _ in range(3):
        ang = rng.uniform(-0.5, 0.5)
        length = rng.uniform(30, 60) * scale
        tip = (cx + math.sin(ang) * length, ground_y - math.cos(ang) * length)
        draw.line([(cx, ground_y), tip], fill=color, width=int(8 * scale), joint="curve")


def _draw_campfire(draw, rng, cx, ground_y, scale):
    draw.rectangle([cx - 40 * scale, ground_y - 10 * scale, cx + 40 * scale, ground_y],
                   fill=(60, 40, 30), outline=INK, width=3)
    for i in range(8):
        ang = i * math.pi / 4
        length = rng.uniform(30, 60) * scale
        tip = (cx + math.sin(ang) * length * 0.3, ground_y - math.cos(ang) * length)
        draw.line([(cx, ground_y), tip], 
                  fill=rng.choice([(255, 80, 20), (255, 140, 30), (255, 200, 40)]),
                  width=int(6 * scale), joint="curve")
    for r in [60, 80, 100]:
        draw.ellipse([cx - r * scale, ground_y - r * scale, 
                      cx + r * scale, ground_y + r * scale],
                     outline=(255, 100, 20), width=2)


def _draw_tent(draw, rng, cx, ground_y, scale):
    w_ = 120 * scale
    h_ = 100 * scale
    pts = [(cx - w_/2, ground_y), (cx, ground_y - h_), (cx + w_/2, ground_y)]
    draw.polygon(pts, fill=(180, 160, 130), outline=INK, width=max(3, round(4 * scale)))
    # door flap
    draw.line([(cx, ground_y), (cx, ground_y - h_ * 0.6)], fill=(150, 130, 100), width=3)


def _draw_bedroll(draw, rng, cx, ground_y, scale):
    w_ = 40 * scale
    h_ = 15 * scale
    draw.rectangle([cx - w_/2, ground_y - h_, cx + w_/2, ground_y], fill=(100, 80, 60), outline=INK, width=2)


def _draw_campfire_scene(draw, rng, w, h, ground_y, ground_color, base_scale):
    _draw_campfire(draw, rng, w * 0.5, ground_y, base_scale * 1.5)
    for i in range(rng.randint(2, 4)):
        x = w * rng.uniform(0.15, 0.85)
        _draw_tent(draw, rng, x, ground_y, base_scale * rng.uniform(0.8, 1.2))
    for _ in range(rng.randint(3, 6)):
        x = w * rng.uniform(0.1, 0.9)
        _draw_bedroll(draw, rng, x, ground_y, base_scale)


def _draw_campfire(draw, rng, cx, ground_y, scale):
    draw.rectangle([cx - 40 * scale, ground_y - 10 * scale, cx + 40 * scale, ground_y],
                   fill=(60, 40, 30), outline=INK, width=3)
    for i in range(8):
        ang = i * math.pi / 4
        length = rng.uniform(30, 60) * scale
        tip = (cx + math.sin(ang) * length * 0.3, ground_y - math.cos(ang) * length)
        draw.line([(cx, ground_y), tip], 
                  fill=rng.choice([(255, 80, 20), (255, 140, 30), (255, 200, 40)]),
                  width=int(6 * scale), joint="curve")
    for r in [60, 80, 100]:
        draw.ellipse([cx - r * scale, ground_y - r * scale, 
                      cx + r * scale, ground_y + r * scale],
                     outline=(255, 100, 20), width=2)


def _draw_city_walls(draw, rng, w, h, ground_y, ground_color, base_scale):
    wall_h = h * rng.uniform(0.25, 0.35)
    wall_y = ground_y - wall_h
    draw.rectangle([0, wall_y, w, ground_y], fill=(140, 135, 130))
    merlon_w = w / 15
    for i in range(15):
        mx = i * merlon_w
        if i % 2 == 0:
            draw.rectangle([mx, wall_y - 25 * base_scale, mx + merlon_w * 0.6, wall_y],
                           fill=(130, 125, 120), outline=INK, width=2)
    gate_x = w * 0.5
    draw.rectangle([gate_x - 60 * base_scale, wall_y, gate_x + 60 * base_scale, ground_y],
                   fill=(80, 60, 40), outline=INK, width=4)
    for side in (-1, 1):
        tx = w * (0.5 + side * 0.35)
        draw.rectangle([tx - 50 * base_scale, wall_y - 80 * base_scale,
                       tx + 50 * base_scale, ground_y], fill=(120, 115, 110), outline=INK, width=3)


def _draw_temple_interior(draw, rng, w, h, ground_y, ground_color, base_scale):
    for i in range(6):
        cx = w * (i + 1) / 7
        draw.rectangle([cx - 25 * base_scale, ground_y - 300 * base_scale,
                       cx + 25 * base_scale, ground_y], fill=(220, 210, 195), outline=INK, width=4)
    draw.rectangle([w * 0.5 - 80 * base_scale, ground_y - 60 * base_scale,
                   w * 0.5 + 80 * base_scale, ground_y], fill=(180, 160, 120), outline=INK, width=4)
    draw.ellipse([w * 0.5 - 40 * base_scale, ground_y - 180 * base_scale,
                  w * 0.5 + 40 * base_scale, ground_y - 100 * base_scale],
                 fill=(200, 190, 170), outline=INK, width=3)


def _draw_battlefield(draw, rng, w, h, ground_y, ground_color, base_scale):
    for _ in range(rng.randint(3, 6)):
        cx = w * rng.uniform(0.1, 0.9)
        cy = ground_y * rng.uniform(0.15, 0.5)
        _draw_smoke_plume(draw, rng, cx, cy, base_scale)
    for _ in range(rng.randint(5, 12)):
        cx = w * rng.uniform(0.05, 0.95)
        _draw_crater(draw, rng, cx, ground_y, base_scale)
    for _ in range(rng.randint(2, 4)):
        cx = w * rng.uniform(0.15, 0.85)
        _draw_distant_fire(draw, rng, cx, ground_y, base_scale)


def _draw_temple(draw, rng, w, h, ground_y, ground_color, base_scale):
    pass  # placeholder


def _compose_scene(rng, scene: Scene, config: PipelineConfig, subject: Optional[str], forced_setting: Optional[str] = None):
    """Draws the background (everything except the focal subject) onto a fresh
    image and returns (background, paint_subject, motion, composition_info).

    - paint_subject(draw) renders the subject onto any draw context, so the
      same composition can be flattened into a still or drawn onto its own
      transparent layer for animation.
    - motion is (amp_x, amp_y, period_x, period_y): how the subject drifts,
      used by the animator. Aquatic subjects float in two axes; land subjects
      bob gently in place.
    - composition_info: dict with 'layout', 'camera_angle', 'subject_position',
      'character_archetype', 'weapon' for downstream animation decisions.
    - forced_setting overrides the scene's own keyword-matched setting - used
      by generate_all/generate_all_clips to apply the whole-video anti-repeat
      pass (see _resolve_setting) without recomputing it here and risking a
      different random.Random draw than the one already made for the video.
    """
    w, h = config.video.resolution
    base = Image.new("RGB", (w, h), SKY)
    draw = ImageDraw.Draw(base)
    base_scale = _frame_base_scale(w, h)

    # --- COMPOSITION VARIETY ---
    # Choose layout based on scene role + mood + randomness.
    # Hook: dramatic close-up or centered impact
    # Build: rule-of-thirds, off-center, environmental
    # Insight: wide, contemplative, pulled back
    # Fight/Crowd: wide to show action
    # Shocked: low angle (looking up) or tight
    mood = _match(scene, _KEYWORD_TO_MOOD) or "neutral"
    role = scene.role

    if role == "hook":
        layout = rng.choice(["centered_dramatic", "rule_of_thirds", "low_angle"])
    elif role == "insight":
        layout = rng.choice(["wide_environmental", "rule_of_thirds", "high_angle"])
    elif mood == "shocked" or _is_fight_scene(scene):
        layout = rng.choice(["wide_environmental", "low_angle", "rule_of_thirds"])
    elif _is_crowd_scene(scene):
        layout = rng.choice(["wide_environmental", "rule_of_thirds"])
    else:
        layout = rng.choice(["rule_of_thirds", "rule_of_thirds", "centered_natural", "wide_environmental"])

    # Resolve historical/mythological character archetype from scene content
    character_archetype = _resolve_character_archetype(scene)
    archetype_outfit, archetype_headwear, archetype_weapon, archetype_pose, _ = _CHARACTER_ARCHETYPES.get(
        character_archetype, _CHARACTER_ARCHETYPES["scholar"]
    )

    composition_info = {"layout": layout, "camera_angle": "eye_level",
                        "character_archetype": character_archetype, "weapon": archetype_weapon}

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
        return base, paint, motion, composition_info

    setting = forced_setting if forced_setting is not None else _setting_for_scene(scene)
    element_scale = base_scale

    if setting in _INTERIOR_VARIANTS:
        # A real interior, not a house prop standing outside under an open
        # sky - see _draw_indoor_scene's docstring for why the old behaviour
        # meant "indoor" scenes still read as outdoor shots.
        ground_y = _draw_indoor_scene(draw, rng, w, h, base_scale, variant=setting)
    else:
        ground_y = round(h * 0.82)
        ground_color = GROUND_COLORS.get(setting, GROUND_COLORS["default"])

        # --- Dynamic Background Selection ---
        # Determine scene type for background based on keywords
        haystack = _scene_haystack(scene)
        scene_type = "default"

        if any(_contains_keyword(haystack, kw) for kw in ("battle", "war", "siege", "army", "battlefield", "front line", "trench")):
            scene_type = "battlefield"
        elif any(_contains_keyword(haystack, kw) for kw in ("camp", "night", "fire", "rest", "campfire", "tent", "bivouac")):
            scene_type = "campfire"
        elif any(_contains_keyword(haystack, kw) for kw in ("city", "walls", "gate", "siege", "castle", "fortress", "wall")):
            scene_type = "city_walls"
        elif any(_contains_keyword(haystack, kw) for kw in ("temple", "altar", "prayer", "worship", "priest", "shrine", "sanctuary")):
            scene_type = "temple"
        elif any(_contains_keyword(haystack, kw) for kw in ("ocean", "sea", "ship", "boat", "underwater", "aquatic", "deep")):
            scene_type = "water"
        elif any(_contains_keyword(haystack, kw) for kw in ("camp", "night", "fire", "rest", "campfire", "tent")):
            scene_type = "campfire"
        elif any(_contains_keyword(haystack, kw) for kw in ("city", "walls", "gate", "siege", "castle", "fortress")):
            scene_type = "city_walls"

        # Sky gradient based on scene type / mood
        if scene_type == "battlefield":
            _draw_sky_gradient(draw, rng, w, ground_y, tint=(200, 80, 60))  # blood-red dawn
        elif scene_type == "campfire":
            _draw_sky_gradient(draw, rng, w, ground_y, tint=(40, 30, 50))   # deep night
        elif scene_type == "temple":
            _draw_sky_gradient(draw, rng, w, ground_y, tint=(255, 240, 200)) # golden
        else:
            _draw_sky_gradient(draw, rng, w, ground_y)
        
        # Clouds scaled to sky height
        n_clouds = max(2, min(8, round(ground_y / (200 * base_scale))))
        for _ in range(n_clouds):
            cx = w * rng.uniform(0.05, 0.95)
            cy = ground_y * rng.uniform(0.05, 0.75)
            _draw_cloud(draw, rng, cx, cy, base_scale * rng.uniform(0.7, 1.5))
        
        # Scene-specific background elements
        if scene_type == "battlefield":
            _draw_battlefield(draw, rng, w, h, ground_y, ground_color, base_scale)
        elif scene_type == "campfire":
            _draw_campfire_scene(draw, rng, w, h, ground_y, ground_color, base_scale)
        elif scene_type == "city_walls":
            _draw_city_walls(draw, rng, w, h, ground_y, ground_color, base_scale)
        elif scene_type == "temple":
            _draw_temple_interior(draw, rng, w, h, ground_y, ground_color, base_scale)
        else:
            # Standard elements
            drawers = _ELEMENT_DRAWERS.get(setting, _ELEMENT_DRAWERS["default"])
            left_positions = [w * 0.10, w * 0.20]
            right_positions = [w * 0.80, w * 0.90]
            li = ri = 0
            for i, drawer in enumerate(drawers):
                if i % 2 == 0 and li < len(left_positions):
                    x = left_positions[li]; li += 1
                elif ri < len(right_positions):
                    x = right_positions[ri]; ri += 1
                else:
                    x = w * rng.uniform(0.1, 0.9)
                drawer(draw, rng, x, ground_y, element_scale * rng.uniform(0.9, 1.3))
        
        _draw_horizon_hills(draw, rng, w, ground_y, ground_color)
        # Small per-scene tint jitter on the ground color - otherwise two
        # consecutive scenes with the same setting (e.g. two "city" scenes in
        # a row) are identical besides prop placement, which is exactly the
        # "same background" complaint even when the setting variety fix
        # above doesn't kick in (a real, non-overloaded match repeating
        # legitimately, e.g. two genuine desert scenes).
        jitter = rng.randint(-14, 14)
        jittered_ground = tuple(max(0, min(255, c + jitter)) for c in ground_color)
        draw.rectangle([0, ground_y, w, h], fill=jittered_ground)
        draw.line([(0, ground_y), (w, ground_y)], fill=INK, width=3)
        texture = _GROUND_TEXTURES.get(setting)
        if texture:
            texture(draw, rng, ground_y, w, h)

    if subject in _SUBJECT_DRAWERS:
        sd = _SUBJECT_DRAWERS[subject]

        def paint(d, phase=0.0):
            # Subject position varies by layout
            if layout == "centered_dramatic":
                cx, cy = w * 0.5, ground_y - 180 * element_scale
                composition_info["camera_angle"] = "low"
            elif layout == "low_angle":
                cx, cy = w * 0.5, ground_y - 220 * element_scale
                composition_info["camera_angle"] = "low"
            elif layout == "rule_of_thirds":
                cx = rng.choice([w // 3, 2 * w // 3])
                cy = ground_y - 180 * element_scale
                composition_info["camera_angle"] = "eye_level"
            elif layout == "high_angle":
                cx, cy = w * 0.5, ground_y - 140 * element_scale
                composition_info["camera_angle"] = "high"
            else:  # wide_environmental
                cx = w * rng.uniform(0.2, 0.8)
                cy = ground_y - 180 * element_scale
                composition_info["camera_angle"] = "high"

            composition_info["subject_position"] = (cx, cy)
            sd(d, rng, cx, cy, element_scale, phase)
    elif _is_fight_scene(scene) or _is_battle_scene(scene):
        is_battle = _is_battle_scene(scene)
        headwear = _match(scene, _KEYWORD_TO_HEADWEAR)
        outfit_a = _match(scene, _KEYWORD_TO_OUTFIT) or (85, 95, 65)
        outfit_b = (150, 60, 60) if outfit_a != (150, 60, 60) else (60, 90, 140)
        
        if is_battle:
            fight_scale = element_scale * 0.9
            cx_a, cx_b = w * 0.35, w * 0.65
        else:
            fight_scale = element_scale * 0.85
            cx_a, cx_b = w * 0.40, w * 0.60

        def paint(d, phase=0.0):
            draw_character(d, rng, cx_a, ground_y, fight_scale, outfit_a, headwear, "neutral", "fighting", phase, facing=1, weapon=archetype_weapon)
            draw_character(d, rng, cx_b, ground_y, fight_scale, outfit_b, headwear, "neutral", "fighting", phase + math.pi, facing=-1, weapon="sword")
            punch_a = max(0.0, math.sin(phase))
            punch_b = max(0.0, math.sin(phase + math.pi))
            if max(punch_a, punch_b) > 0.9:
                _draw_impact_burst(d, (cx_a + cx_b) / 2, ground_y - 235 * fight_scale, fight_scale)
            
            # Supporting cast for battles
            if _is_battle_scene(scene):
                support_count = rng.randint(10, 20)
                support_positions = []
                for i in range(support_count):
                    if i % 2 == 0:
                        x = w * rng.uniform(0.08, 0.30)
                        facing = 1
                    else:
                        x = w * rng.uniform(0.70, 0.92)
                        facing = -1
                    s = element_scale * rng.uniform(0.4, 0.7)
                    support_positions.append((x, s, facing))
                
                soldier_outfits = [(85, 95, 65), (60, 80, 100), (100, 60, 60), (70, 70, 70)]
                for i, (x, s, facing) in enumerate(support_positions):
                    outfit = rng.choice(soldier_outfits)
                    pose = rng.choice(["aiming", "charging", "standing"])
                    weapon = "crossbow" if pose == "aiming" else rng.choice(["spear", "sword", "axe"])
                    _draw_soldier(d, rng, x, ground_y, s, outfit, phase + i * 0.5, 
                                  facing=facing, pose=pose, weapon=weapon)
        
        composition_info["camera_angle"] = "eye_level"
        composition_info["subject_position"] = ((cx_a + cx_b) / 2, ground_y)
    else:
        # Use archetype for outfit/headwear/weapon, fallback to keyword matching
        outfit = _match(scene, _KEYWORD_TO_OUTFIT) or archetype_outfit
        headwear = _match(scene, _KEYWORD_TO_HEADWEAR) or archetype_headwear
        mood = _match(scene, _KEYWORD_TO_MOOD) or "neutral"
        pose = archetype_pose if scene.role == "hook" else rng.choice(["sides", "raised", "crossed"])
        crowd = _is_crowd_scene(scene)
        crowd_specs = []
        if crowd:
            positions = [w * 0.14, w * 0.24, w * 0.76, w * 0.86, w * 0.32, w * 0.68]
            for idx in range(rng.randint(3, 5)):
                x = positions[idx % len(positions)] + rng.uniform(-w * 0.03, w * 0.03)
                crowd_specs.append((x, rng.choice(_CROWD_COLORS), idx, element_scale * rng.uniform(0.45, 0.6)))

        character_scale = element_scale * HUMAN_SCALE * rng.uniform(0.85, 1.3)

        def paint(d, phase=0.0):
            for x, color, idx, cscale in crowd_specs:
                _draw_background_person(d, rng, x, ground_y, cscale, color, phase, idx)

            # Subject position varies by layout
            if layout == "centered_dramatic":
                cx = w * 0.5
                composition_info["camera_angle"] = "low"
            elif layout == "low_angle":
                cx = w * 0.5
                composition_info["camera_angle"] = "low"
            elif layout == "rule_of_thirds":
                cx = rng.choice([w // 3, 2 * w // 3])
                composition_info["camera_angle"] = "eye_level"
            elif layout == "high_angle":
                cx = w * 0.5
                composition_info["camera_angle"] = "high"
            else:  # wide_environmental
                cx = w * rng.uniform(0.25, 0.75)
                composition_info["camera_angle"] = "high"

            cy = ground_y - 180 * element_scale
            composition_info["subject_position"] = (cx, cy)
            draw_character(d, rng, cx, cy, character_scale, outfit, headwear, mood, pose, phase, weapon=archetype_weapon)

    motion = (0.0, 24 * base_scale, 0.0, 2.6)  # in-place bob - doubled from 12px, which barely registered on screen
    return base, paint, motion, composition_info


def _resolve_settings_for_video(scenes: List[Scene]) -> List[str]:
    """Precomputes each scene's setting for a whole video in one pass so the
    anti-repeat rule in _resolve_setting can see the *previous* scene's
    already-resolved setting - not just its own keyword match - without
    changing generate_scene_image/generate_scene_clip's return type (they're
    called independently per scene, so this can't live inside them). Uses its
    own throwaway random.Random(index) per scene, entirely separate from the
    rng each scene's actual drawing uses, so it doesn't perturb any existing
    per-scene rendering determinism."""
    settings = []
    prev: Optional[str] = None
    for i, scene in enumerate(scenes):
        setting = _resolve_setting(scene, prev, random.Random(i))
        settings.append(setting)
        prev = setting
    return settings


def generate_scene_image(
    scene: Scene, index: int, config: PipelineConfig, work_dir: Path,
    subject_fallback: Optional[str] = None, forced_setting: Optional[str] = None,
) -> Path:
    rng = random.Random(index)
    subject = _resolve_subject(scene, index, subject_fallback)
    base, paint, _motion, _comp = _compose_scene(rng, scene, config, subject, forced_setting=forced_setting)
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


def _build_sprite_frames(
    rng: random.Random, paint, w: int, h: int, work_dir: Path, index: int,
    bubbles: bool = False, loop_frames: int = _LOOP_FRAMES,
) -> Path:
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
    like a slideshow" for every character-driven scene.

    `loop_frames` defaults to the module-wide _LOOP_FRAMES but callers can
    vary it per scene (see generate_scene_clip) so every scene in a video
    doesn't repeat the exact same 2-second cycle - a fixed loop length across
    a whole ~7 minute video is itself a source of monotony independent of
    the motion's amplitude."""
    frame_dir = work_dir / f"scene_{index:02d}_frames"
    frame_dir.mkdir(exist_ok=True)
    bubble_specs = _rising_bubbles(rng, w, h) if bubbles else None

    for i in range(loop_frames):
        t = i / _LOOP_FPS
        phase = 2 * math.pi * i / loop_frames
        frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(frame)
        if bubble_specs is not None:
            _draw_bubbles(d, bubble_specs, t, h)
        paint(d, phase)
        frame.save(frame_dir / f"f_{i:03d}.png")

    return frame_dir / "f_%03d.png"


def _is_dramatic_beat(scene: Scene) -> bool:
    """True for the video's hook (always scene 0, and the single moment that
    decides whether someone keeps watching at all) and for build scenes
    whose mood/content is a shock/twist/fight beat - see script_writer's
    prompt on the 20-30s retention cliff this is meant to punctuate. Used by
    generate_scene_clip to add a quick flash-in on exactly these scenes:
    every other scene stays plain so the flash still reads as a deliberate
    accent instead of a tic repeated every few seconds."""
    return scene.role == "hook" or _match(scene, _KEYWORD_TO_MOOD) == "shocked" or _is_fight_scene(scene)


def generate_scene_clip(
    scene: Scene, index: int, config: PipelineConfig, work_dir: Path,
    duration: float, subject_fallback: Optional[str] = None, forced_setting: Optional[str] = None,
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
    base, paint, (ax, ay, px, py), _comp = _compose_scene(rng, scene, config, subject, forced_setting=forced_setting)

    bg_path = work_dir / f"scene_{index:02d}_bg.jpg"
    base.save(bg_path, quality=90)

    if subject in _AQUATIC_SUBJECTS:
        # Aquatic creatures have phase-varying paint() (tentacle-sway/fin-wiggle
        # plus rising bubbles), so they render as a looping animated frame
        # sequence rather than one frozen pose.
        # Vary the loop length +/-40% per scene (still seeded, so
        # deterministic) - otherwise every scene in the whole video repeats
        # the identical 2-second cycle, which reads as a metronome over a
        # long scene and as repetitive from scene to scene.
        loop_frames = max(4, round(_LOOP_FRAMES * rng.uniform(0.8, 1.4)))
        frame_pattern = _build_sprite_frames(rng, paint, w, h, work_dir, index, bubbles=True, loop_frames=loop_frames)
        sprite_input = ["-framerate", str(_LOOP_FPS), "-stream_loop", "-1", "-i", str(frame_pattern)]
    else:
        # Land characters (including subject=None for generic narrator) use a
        # single static sprite with gentle vertical bob only — no horizontal
        # sliding across the screen.
        sprite = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        paint(ImageDraw.Draw(sprite))
        sprite_path = work_dir / f"scene_{index:02d}_sprite.png"
        sprite.save(sprite_path)
        sprite_input = ["-loop", "1", "-i", str(sprite_path)]

    # Ken Burns: render the background oversized and slide/zoom a w x h
    # window across it over the scene's duration, instead of feeding the
    # native-resolution still straight through. Direction/axis/zoom amount
    # are seeded per-scene (rng, and index parity for direction) so
    # consecutive scenes don't all crawl the same way. Dramatic beats get a
    # noticeably punchier pan range than an ordinary scene - more oversized
    # source to move across in the same duration means faster apparent
    # motion, which reads as urgency/energy right where the script wants it
    # (the hook, or a shock/twist/fight beat) rather than the same gentle
    # drift everywhere flattening every moment to the same energy.
    dramatic = _is_dramatic_beat(scene)
    zoom = rng.uniform(1.22, 1.38) if dramatic else rng.uniform(1.10, 1.22)
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

    # A quick flash-in from white on the hook (every video's make-or-break
    # first moment) and on shock/twist/fight beats elsewhere - a real,
    # deliberate punctuation mark instead of hoping the character's face
    # alone (mood="shocked" swaps to X-eyes) reads as dramatic at video
    # scale. Capped to a fraction of the scene's own length so it can never
    # eat a very short scene's whole runtime.
    if dramatic:
        flash_d = min(0.18, max(0.06, duration * 0.12))
        final_filter = (
            f"[bg][1:v]overlay=x={subj_x}:y={subj_y}:eval=frame[ov];"
            f"[ov]fade=t=in:st=0:d={flash_d:.3f}:color=white[v]"
        )
    else:
        final_filter = f"[bg][1:v]overlay=x={subj_x}:y={subj_y}:eval=frame[v]"

    out_path = work_dir / f"scene_{index:02d}_anim.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(bg_path),
        *sprite_input,
        "-filter_complex",
        f"[0:v]scale={ow}:{oh},fps={config.video.fps},"
        f"crop=w={w}:h={h}:x='{bg_x}':y='{bg_y}'[bg];"
        f"{final_filter}",
        "-map", "[v]", "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"scene animation ffmpeg failed:\n{' '.join(cmd)}\n\n{result.stderr[-3000:]}")
    return out_path


def generate_all(scenes: List[Scene], config: PipelineConfig, work_dir: Path, title: str = "") -> List[Path]:
    # Fallback subject from the whole script (plus the title, the strongest
    # signal of what the video's actually about) so a single-subject video
    # (e.g. about an octopus) shows it consistently, not only on sentences
    # that name it - see _dominant_subject's docstring for why a title/
    # scene-fraction bar is required rather than any keyword hit at all.
    fallback = _dominant_subject(scenes, extra_text=title)
    settings = _resolve_settings_for_video(scenes)
    return [
        generate_scene_image(scene, i, config, work_dir, subject_fallback=fallback, forced_setting=settings[i])
        for i, scene in enumerate(scenes)
    ]


def generate_all_clips(
    scenes: List[Scene], durations: List[float], config: PipelineConfig, work_dir: Path, title: str = "",
) -> List[Path]:
    """Animated per-scene clips (one MP4 each), sized to each scene's audio
    duration. Same subject/fallback logic as generate_all."""
    fallback = _dominant_subject(scenes, extra_text=title)
    settings = _resolve_settings_for_video(scenes)
    return [
        generate_scene_clip(scene, i, config, work_dir, dur, subject_fallback=fallback, forced_setting=settings[i])
        for i, (scene, dur) in enumerate(zip(scenes, durations))
    ]
