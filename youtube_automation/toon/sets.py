"""Layered parallax backgrounds, one builder per `setting` (the same keys the
legacy renderer uses). Each layer is rendered ONCE to a tileable skia Image and
then just transformed per frame, so a rich set costs almost nothing to animate."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import skia

from .art import INK, Color, col, fill, glow, inked, inked_circle, inked_oval, poly_path, shade, stroke, vgradient

OVERSCAN = 1.5


@dataclass
class Layer:
    image: "skia.Image"
    parallax: float
    drift: float = 0.0       # px/s of autonomous horizontal drift (clouds)
    front: bool = False      # drawn after the characters


@dataclass
class SceneSet:
    layers: List[Layer]
    ground_y: float
    particles: str
    tod: str
    lights: List[Tuple[float, float, Color, float]] = field(default_factory=list)  # (x, y, colour, radius) flickering lamps
    tile_w: int = 0
    interior: bool = False


def _blend(a: Color, b: Color, t: float) -> Color:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def tint(c: Color, tod: str) -> Color:
    if tod == "dusk":
        return shade(_blend(c, (255, 140, 96), 0.28), -0.08)
    if tod == "night":
        return shade(_blend(c, (28, 38, 96), 0.58), -0.32)
    return c


_SKY = {
    "snow": ((165, 192, 222), (238, 244, 250)), "desert": ((238, 188, 118), (252, 228, 172)),
    "ruins": ((128, 112, 112), (226, 160, 118)), "mythic": ((160, 132, 226), (255, 216, 192)),
    "ancient": ((150, 200, 240), (252, 232, 190)), "dungeon": ((20, 20, 30), (40, 40, 52)),
}
_DEFAULT_SKY = ((104, 182, 238), (224, 242, 252))
_DUSK_SKY = ((70, 58, 130), (252, 156, 92))
_NIGHT_SKY = ((10, 14, 38), (44, 56, 108))


def sky_colors(setting: str, tod: str) -> Tuple[Color, Color]:
    if tod == "dusk":
        return _DUSK_SKY
    if tod == "night":
        return _NIGHT_SKY
    return _SKY.get(setting, _DEFAULT_SKY)


class _Surf:
    def __init__(self, w: int, h: int):
        self.surface = skia.Surface(w, h)
        self.c = self.surface.getCanvas()
        self.w, self.h = w, h

    def image(self):
        return self.surface.makeImageSnapshot()

    def rep(self, fn: Callable[[float], None], x: float, span: float = 0.0):
        """Draw a prop and its wrapped copies so the layer tiles seamlessly."""
        for dx in (-self.w, 0, self.w):
            fn(x + dx)


# ---- props -----------------------------------------------------------------------------------

def tree(c, x, gy, s, leaf: Color, o):
    c.drawRect(skia.Rect(x - 5 * s, gy - 38 * s, x + 5 * s, gy), fill((110, 78, 52)))
    c.drawRect(skia.Rect(x - 5 * s, gy - 38 * s, x + 5 * s, gy), stroke(INK, o))
    for dx, dy, r in ((0, -62, 30), (-20, -48, 22), (20, -48, 22)):
        inked_circle(c, x + dx * s, gy + dy * s, r * s, leaf, o)
    inked_circle(c, x, gy - 62 * s, 30 * s, leaf, 0)


def pine(c, x, gy, s, leaf: Color, o, snow=False):
    c.drawRect(skia.Rect(x - 4 * s, gy - 20 * s, x + 4 * s, gy), fill((96, 70, 50)))
    for i, (w, y) in enumerate(((34, 18), (28, 44), (21, 68))):
        pts = [(x - w * s, gy - y * s), (x, gy - (y + 38) * s), (x + w * s, gy - y * s)]
        inked(c, poly_path(pts), leaf, o)
        if snow:
            c.drawPath(poly_path([(x - w * 0.5 * s, gy - (y + 18) * s), (x, gy - (y + 38) * s), (x + w * 0.5 * s, gy - (y + 18) * s)]), fill((250, 252, 255)))


def house(c, x, gy, s, wall: Color, o):
    inked(c, poly_path([(x - 34 * s, gy), (x - 34 * s, gy - 38 * s), (x + 34 * s, gy - 38 * s), (x + 34 * s, gy)]), wall, o)
    inked(c, poly_path([(x - 42 * s, gy - 36 * s), (x, gy - 70 * s), (x + 42 * s, gy - 36 * s)]), shade((190, 90, 70), 0), o)
    inked(c, poly_path([(x - 8 * s, gy), (x - 8 * s, gy - 22 * s), (x + 8 * s, gy - 22 * s), (x + 8 * s, gy)]), (110, 76, 52), o * 0.8)
    inked(c, poly_path([(x + 16 * s, gy - 18 * s), (x + 16 * s, gy - 30 * s), (x + 28 * s, gy - 30 * s), (x + 28 * s, gy - 18 * s)]), (255, 232, 150), o * 0.8)


def mountain(c, x, gy, s, base: Color, o, cap=True):
    pts = [(x - 130 * s, gy), (x - 20 * s, gy - 150 * s), (x + 20 * s, gy - 132 * s), (x + 130 * s, gy)]
    inked(c, poly_path(pts), base, o)
    if cap:
        c.drawPath(poly_path([(x - 44 * s, gy - 112 * s), (x - 20 * s, gy - 150 * s), (x + 20 * s, gy - 132 * s), (x + 36 * s, gy - 104 * s), (x + 8 * s, gy - 116 * s), (x - 14 * s, gy - 104 * s)]), fill((248, 250, 255)))


def building(c, x, gy, w, h, wall: Color, o, tod="day", rng=None):
    inked(c, poly_path([(x - w / 2, gy), (x - w / 2, gy - h), (x + w / 2, gy - h), (x + w / 2, gy)]), wall, o)
    lit = (255, 226, 130) if tod != "day" else shade(wall, 0.35)
    rows, cols = int(h // 26), max(1, int(w // 22))
    for r in range(1, rows):
        for k in range(cols):
            wx = x - w / 2 + 8 + k * (w - 16) / max(1, cols)
            on = (rng.random() < 0.55) if rng else True
            c.drawRect(skia.Rect(wx, gy - h + r * 26, wx + 10, gy - h + r * 26 + 13), fill(lit if on else shade(wall, -0.18)))


def column(c, x, gy, h, w, o, stone=(224, 214, 196)):
    inked(c, poly_path([(x - w / 2, gy), (x - w / 2 + 2, gy - h), (x + w / 2 - 2, gy - h), (x + w / 2, gy)]), stone, o)
    c.drawRect(skia.Rect(x - w * 0.7, gy - h - 7, x + w * 0.7, gy - h), fill(shade(stone, -0.08)))
    c.drawRect(skia.Rect(x - w * 0.7, gy - h - 7, x + w * 0.7, gy - h), stroke(INK, o))
    for k in (-0.2, 0.2):
        c.drawLine(x + k * w, gy - 6, x + k * w, gy - h + 4, stroke(shade(stone, -0.18), 1.6))


def temple(c, x, gy, s, o, stone=(226, 214, 192)):
    for i in range(5):
        column(c, x + (i - 2) * 30 * s, gy, 78 * s, 16 * s, o, stone)
    inked(c, poly_path([(x - 90 * s, gy - 82 * s), (x, gy - 118 * s), (x + 90 * s, gy - 82 * s)]), shade(stone, -0.06), o)
    c.drawRect(skia.Rect(x - 92 * s, gy - 86 * s, x + 92 * s, gy - 76 * s), fill(shade(stone, -0.12)))
    c.drawRect(skia.Rect(x - 92 * s, gy - 86 * s, x + 92 * s, gy - 76 * s), stroke(INK, o))


def pyramid(c, x, gy, s, base: Color, o):
    inked(c, poly_path([(x - 120 * s, gy), (x, gy - 130 * s), (x + 120 * s, gy)]), base, o)
    c.drawPath(poly_path([(x, gy - 130 * s), (x + 120 * s, gy), (x + 30 * s, gy)]), fill(shade(base, -0.16)))
    c.drawPath(poly_path([(x - 120 * s, gy), (x, gy - 130 * s), (x + 120 * s, gy)], True), stroke(INK, o))


def castle(c, x, gy, s, wall: Color, o):
    inked(c, poly_path([(x - 70 * s, gy), (x - 70 * s, gy - 70 * s), (x + 70 * s, gy - 70 * s), (x + 70 * s, gy)]), wall, o)
    for tx in (-78, 0, 78):
        h = 118 if tx == 0 else 96
        inked(c, poly_path([(x + (tx - 20) * s, gy), (x + (tx - 20) * s, gy - h * s), (x + (tx + 20) * s, gy - h * s), (x + (tx + 20) * s, gy)]), shade(wall, 0.05), o)
        inked(c, poly_path([(x + (tx - 26) * s, gy - h * s), (x + tx * s, gy - (h + 34) * s), (x + (tx + 26) * s, gy - h * s)]), (176, 78, 92), o)
    inked(c, poly_path([(x - 14 * s, gy), (x - 14 * s, gy - 34 * s), (x + 14 * s, gy - 34 * s), (x + 14 * s, gy)]), (96, 70, 52), o * 0.8)


def capitol(c, x, gy, s, o, stone=(232, 230, 224)):
    inked(c, poly_path([(x - 110 * s, gy), (x - 110 * s, gy - 56 * s), (x + 110 * s, gy - 56 * s), (x + 110 * s, gy)]), stone, o)
    for i in range(6):
        column(c, x + (i - 2.5) * 30 * s, gy, 56 * s, 11 * s, o, stone)
    p = skia.Path()
    p.addArc(skia.Rect(x - 42 * s, gy - 118 * s, x + 42 * s, gy - 38 * s), 180, 180)
    p.close()
    inked(c, p, shade(stone, -0.05), o)
    c.drawLine(x, gy - 118 * s, x, gy - 134 * s, stroke(INK, o))


def ship(c, x, gy, s, o, hull=(120, 84, 60)):
    inked(c, poly_path([(x - 70 * s, gy - 18 * s), (x + 70 * s, gy - 18 * s), (x + 50 * s, gy + 6 * s), (x - 50 * s, gy + 6 * s)]), hull, o)
    c.drawLine(x, gy - 18 * s, x, gy - 112 * s, stroke(INK, o * 1.5))
    inked(c, poly_path([(x + 3 * s, gy - 104 * s), (x + 56 * s, gy - 52 * s), (x + 3 * s, gy - 28 * s)]), (248, 244, 232), o)
    inked(c, poly_path([(x - 3 * s, gy - 94 * s), (x - 44 * s, gy - 50 * s), (x - 3 * s, gy - 32 * s)]), (240, 234, 220), o)


def ruin(c, x, gy, s, o, stone=(196, 186, 170)):
    for dx, h in ((-40, 70), (-10, 42), (24, 88), (56, 30)):
        w = 22 * s
        inked(c, poly_path([(x + dx * s - w / 2, gy), (x + dx * s - w / 2, gy - h * s), (x + dx * s - w / 2 + w * 0.4, gy - h * s - 7 * s), (x + dx * s + w / 2, gy - h * s + 6 * s), (x + dx * s + w / 2, gy)]), stone, o)
    inked(c, poly_path([(x - 60 * s, gy), (x - 52 * s, gy - 12 * s), (x + 70 * s, gy - 8 * s), (x + 76 * s, gy)]), shade(stone, -0.1), o)


def cloud(c, x, y, s):
    for dx, dy, r in ((-24, 4, 18), (0, -6, 24), (26, 2, 19), (8, 8, 18)):
        c.drawCircle(x + dx * s, y + dy * s, r * s, fill((255, 255, 255), 235))


def crates(c, x, gy, s, o):
    for dx, dy, w in ((0, 0, 30), (32, 0, 28), (14, -28, 26)):
        inked(c, poly_path([(x + dx * s, gy + dy * s), (x + dx * s, gy + (dy - w) * s), (x + (dx + w) * s, gy + (dy - w) * s), (x + (dx + w) * s, gy + dy * s)]), (176, 130, 84), o)
        c.drawLine(x + dx * s, gy + (dy - w) * s, x + (dx + w) * s, gy + dy * s, stroke(shade((176, 130, 84), -0.3), o * 0.7))


# ---- layer builders ----------------------------------------------------------------------------

_EXTERIOR_PROPS = {  # setting -> (far prop list, mid prop list)
    "default": (["hills"], [house, tree, tree]), "snow": (["mountains"], [pine, pine, house]),
    "mountain": (["mountains"], [pine, tree]), "ruins": (["hills"], [ruin, ruin]),
    "forest": (["hills"], [tree, tree, pine, tree]), "desert": (["dunes"], [ruin, pyramid]),
    "water": (["horizon"], [ship]), "harbor": (["horizon"], [ship, crates]),
    "palace": (["hills"], [castle]), "ancient": (["dunes"], [temple, pyramid]),
    "city": (["skyline"], [building, building, building]), "government": (["skyline"], [capitol]),
    "mythic": (["clouds"], [temple]), "default2": (["hills"], [tree]),
}
INTERIOR = {"indoor", "dungeon", "courtroom"}


def _hills(sf: _Surf, gy: float, base: Color, amp: float, seed: int, o=0):
    p = skia.Path()
    p.moveTo(0, sf.h)
    n = 60
    for i in range(n + 1):
        x = sf.w * i / n
        a = 2 * math.pi * i / n
        y = gy - amp * (0.55 + 0.25 * math.sin(a * 2 + seed) + 0.15 * math.sin(a * 5 + seed * 2.1) + 0.08 * math.sin(a * 11 + seed))
        p.lineTo(x, y)
    p.lineTo(sf.w, sf.h)
    p.close()
    sf.c.drawPath(p, fill(base))


def build_set(setting: str, tod: str, w: int, h: int, rng: random.Random) -> SceneSet:
    LW = int(w * OVERSCAN)
    interior = setting in INTERIOR
    gy = h * (0.74 if interior else 0.78)
    s = h / 1080
    from ..procedural_illustration import GROUND_COLORS  # shared palette keys with the legacy renderer
    ground = tint(GROUND_COLORS.get(setting, GROUND_COLORS["default"]), tod)
    layers: List[Layer] = []
    lights: List[Tuple[float, float, Color, float]] = []
    particles = {"snow": "snow", "ruins": "embers", "desert": "dust", "mythic": "sparkles", "water": "birds",
                 "harbor": "birds", "dungeon": "dust", "courtroom": "dust", "indoor": "dust"}.get(setting, "motes")
    if tod == "night" and not interior:
        particles = "fireflies"

    # sky (static gradient + sun/moon/stars)
    sky = _Surf(LW, h)
    top, bot = sky_colors(setting, tod)
    sky.c.drawRect(skia.Rect(0, 0, LW, h), skia.Paint(Shader=vgradient(top, bot, 0, gy)))
    if not interior:
        if tod == "night":
            for _ in range(90):
                sky.c.drawCircle(rng.uniform(0, LW), rng.uniform(0, gy * 0.8), rng.uniform(0.8, 2.2), fill((255, 255, 240), rng.randint(120, 255)))
            glow(sky.c, LW * 0.7, h * 0.2, 120 * s, (200, 215, 255), 110)
            inked_circle(sky.c, LW * 0.7, h * 0.2, 46 * s, (244, 244, 224), 0)
        else:
            sun = (255, 238, 170) if tod == "day" else (255, 190, 110)
            sx = LW * (0.72 if tod == "day" else 0.3)
            sy = h * (0.18 if tod == "day" else 0.5)
            glow(sky.c, sx, sy, 190 * s, sun, 120)
            sky.c.drawCircle(sx, sy, 52 * s, fill(sun))
    layers.append(Layer(sky.image(), 0.04))

    if interior:
        _build_interior(setting, tod, LW, h, gy, s, ground, layers, lights, rng)
    else:
        # drifting clouds
        if setting not in {"ruins"} or tod == "day":
            cl = _Surf(LW, h)
            for _ in range(7):
                cloud(cl.c, rng.uniform(0, LW), rng.uniform(h * 0.05, h * 0.38), rng.uniform(1.2, 2.4) * s * (0.6 if tod == "night" else 1))
            if tod != "day":
                cl.c.drawRect(skia.Rect(0, 0, LW, h), skia.Paint(Color=col(tint((255, 255, 255), tod), 150), BlendMode=skia.BlendMode.kSrcATop))
            layers.append(Layer(cl.image(), 0.10, drift=12.0))
        far_kinds, mid_props = _EXTERIOR_PROPS.get(setting, _EXTERIOR_PROPS["default"])
        # far silhouettes
        far = _Surf(LW, h)
        far_col = tint(shade(top, 0.0) if setting == "mythic" else _blend(top, (96, 130, 110), 0.55), tod)
        kind = far_kinds[0]
        if kind in {"hills", "dunes"}:
            _hills(far, gy, tint(_blend(far_col, (200, 210, 200), 0.2), tod) if kind == "hills" else tint((236, 196, 130), tod), 170 * s, rng.randint(0, 9))
        elif kind == "mountains":
            for i in range(7):
                mountain(far.c, i * LW / 7 + rng.uniform(-30, 30), gy, rng.uniform(1.0, 1.7) * s, tint(_blend((140, 150, 175), top, 0.25), tod), 0, cap=True)
        elif kind == "skyline":
            x = 0.0
            while x < LW:
                bw = rng.uniform(70, 130) * s
                building(far.c, x + bw / 2, gy, bw, rng.uniform(150, 340) * s, tint((118, 130, 156), tod), 0, tod, rng)
                x += bw
        elif kind == "horizon":
            far.c.drawRect(skia.Rect(0, gy - 28 * s, LW, h), fill(tint((96, 166, 214), tod)))
        elif kind == "clouds":
            for _ in range(10):
                cloud(far.c, rng.uniform(0, LW), gy - rng.uniform(0, 80) * s, rng.uniform(1.6, 3.0) * s)
        layers.append(Layer(far.image(), 0.22))
        # mid props
        mid = _Surf(LW, h)
        n = 6 if setting not in {"palace", "government", "ancient", "water", "mythic"} else 3
        leaf = tint({"snow": (62, 118, 96), "forest": (66, 140, 78), "ruins": (110, 120, 76), "mountain": (74, 128, 88)}.get(setting, (92, 168, 96)), tod)
        wall = tint((238, 222, 190), tod)
        stone = tint((226, 214, 192), tod)
        for i in range(n):
            x = (i + rng.uniform(0.2, 0.8)) * LW / n
            fn = rng.choice(mid_props)
            sc = rng.uniform(0.9, 1.3) * s * 2.0
            if fn is tree:
                mid.rep(lambda xx: tree(mid.c, xx, gy - 8, sc, leaf, 3.5), x)
            elif fn is pine:
                mid.rep(lambda xx: pine(mid.c, xx, gy - 8, sc, leaf, 3.5, snow=(setting == "snow")), x)
            elif fn is house:
                mid.rep(lambda xx: house(mid.c, xx, gy - 8, sc, wall, 3.5), x)
            elif fn is building:
                bw, bh = rng.uniform(100, 160) * s * 1.2, rng.uniform(260, 460) * s
                mid.rep(lambda xx: building(mid.c, xx, gy - 6, bw, bh, tint((156, 164, 186), tod), 3.5, tod, rng), x)
            elif fn is ruin:
                mid.rep(lambda xx: ruin(mid.c, xx, gy - 6, sc, 3.5, tint((196, 186, 170), tod)), x)
            elif fn is castle:
                mid.rep(lambda xx: castle(mid.c, xx, gy - 6, sc * 1.1, tint((206, 198, 186), tod), 3.5), x)
            elif fn is capitol:
                mid.rep(lambda xx: capitol(mid.c, xx, gy - 6, sc * 1.2, 3.5, stone), x)
            elif fn is temple:
                mid.rep(lambda xx: temple(mid.c, xx, gy - 6, sc, 3.5, stone), x)
            elif fn is pyramid:
                mid.rep(lambda xx: pyramid(mid.c, xx, gy - 6, sc, tint((226, 196, 132), tod), 3.5), x)
            elif fn is ship:
                mid.rep(lambda xx: ship(mid.c, xx, gy + 2, sc, 3.5), x)
            elif fn is crates:
                mid.rep(lambda xx: crates(mid.c, xx, gy - 4, sc, 3.5), x)
        layers.append(Layer(mid.image(), 0.55))
        if tod != "day":
            lights += [(w * f, gy - 90 * s, (255, 214, 120), 70 * s) for f in (0.15, 0.55, 0.85)] if tod == "night" and setting in {"city", "harbor", "government", "default"} else []

    # ground band (parallax 1.0 - the plane the characters stand on)
    g = _Surf(LW, h)
    g.c.drawRect(skia.Rect(0, gy, LW, h), skia.Paint(Shader=vgradient(ground, shade(ground, -0.18), gy, h)))
    g.c.drawRect(skia.Rect(0, gy - 3, LW, gy + 4), fill(shade(ground, 0.22)))
    g.c.drawLine(0, gy, LW, gy, stroke(INK, 3.5))
    for _ in range(46):
        gx, gyy = rng.uniform(0, LW), rng.uniform(gy + 14, h - 6)
        g.c.drawLine(gx, gyy, gx + rng.uniform(8, 22) * s, gyy, stroke(shade(ground, -0.2 if interior else -0.14), 3))
    layers.append(Layer(g.image(), 1.0))

    # foreground silhouettes in front of the characters (depth!)
    if not interior:
        fr = _Surf(LW, h)
        dark = tint(shade(ground, -0.55), tod)
        for _ in range(9):
            fx = rng.uniform(0, LW)
            fr.rep(lambda xx: [fr.c.drawPath(poly_path([(xx + dx * s, h + 4), (xx + (dx + 4) * s, h - rng.uniform(40, 120) * s), (xx + (dx + 10) * s, h + 4)]), fill(dark)) for dx in range(0, 36, 9)], fx)
        layers.append(Layer(fr.image(), 1.45, front=True))
    return SceneSet(layers=layers, ground_y=gy, particles=particles, tod=tod, lights=lights, tile_w=LW, interior=interior)


def _build_interior(setting, tod, LW, h, gy, s, ground, layers, lights, rng):
    wall_c = {"dungeon": (78, 80, 92), "courtroom": (150, 112, 74), "indoor": (214, 196, 168)}[setting]
    wall_c = tint(wall_c, "night" if tod == "night" else "day")
    wl = _Surf(LW, h)
    wl.c.drawRect(skia.Rect(0, 0, LW, gy), skia.Paint(Shader=vgradient(shade(wall_c, 0.1), shade(wall_c, -0.15), 0, gy)))
    if setting == "dungeon":
        for ry in range(0, int(gy), int(46 * s) or 46):
            wl.c.drawLine(0, ry, LW, ry, stroke(shade(wall_c, -0.3), 3))
            for rx in range(int((ry // (46 * s or 46)) % 2 * 40), LW, int(90 * s) or 90):
                wl.c.drawLine(rx, ry, rx, ry + 46 * s, stroke(shade(wall_c, -0.3), 3))
        for i in range(4):  # barred windows + torches
            bx = (i + 0.5) * LW / 4
            wl.c.drawRect(skia.Rect(bx - 40 * s, gy * 0.2, bx + 40 * s, gy * 0.2 + 96 * s), fill((14, 16, 26)))
            for k in range(-1, 2):
                wl.c.drawLine(bx + k * 20 * s, gy * 0.2, bx + k * 20 * s, gy * 0.2 + 96 * s, stroke((110, 110, 120), 5))
            tx = bx + LW / 8
            wl.c.drawLine(tx, gy * 0.42, tx, gy * 0.42 + 40 * s, stroke((96, 70, 50), 7))
            lights.append((tx % (LW), gy * 0.4, (255, 170, 70), 130 * s))
    elif setting == "courtroom":
        wl.c.drawRect(skia.Rect(0, gy * 0.62, LW, gy), fill(shade(wall_c, -0.18)))
        for i in range(8):
            px = (i + 0.5) * LW / 8
            column(wl.c, px, gy * 0.62, gy * 0.5, 34 * s, 3.5, shade(wall_c, 0.25))
        wl.c.drawRect(skia.Rect(LW * 0.4, gy * 0.18, LW * 0.6, gy * 0.42), fill((210, 190, 120)))
        inked_circle(wl.c, LW * 0.5, gy * 0.3, 48 * s, (230, 214, 150), 4)
    else:
        for i in range(4):
            bx = (i + 0.5) * LW / 4
            wl.c.drawRect(skia.Rect(bx - 70 * s, gy * 0.18, bx + 70 * s, gy * 0.58), fill((176, 218, 244)))
            wl.c.drawRect(skia.Rect(bx - 70 * s, gy * 0.18, bx + 70 * s, gy * 0.58), stroke(INK, 5))
            wl.c.drawLine(bx, gy * 0.18, bx, gy * 0.58, stroke(INK, 4))
            wl.c.drawLine(bx - 70 * s, gy * 0.38, bx + 70 * s, gy * 0.38, stroke(INK, 4))
        wl.c.drawRect(skia.Rect(0, gy * 0.74, LW, gy * 0.80), fill(shade(wall_c, -0.22)))
    layers.append(Layer(wl.image(), 0.35))
