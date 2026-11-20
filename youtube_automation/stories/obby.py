"""Procedural third-person 'obby' parkour background for story Shorts.

Used when no real recorded gameplay clips are available. A blocky avatar runs
and jumps across floating coloured platforms in a sky, filmed by a chase
camera. Everything is original geometry (no game assets, logos or textures).

    frames(duration, w, h, fps, seed)  -> iterator of RGBA numpy frames
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterator, List, Tuple

import numpy as np
import skia

SPEED = 16.0                  # studs/s - a typical default walk speed in block games
SKY_TOP, SKY_BOTTOM = (70, 160, 250), (196, 232, 255)
PALETTE = [(88, 200, 92), (66, 135, 245), (250, 196, 45), (240, 120, 200), (150, 110, 240), (255, 150, 60)]
KILL = (235, 45, 45)
CHECKPOINT = (235, 235, 240)
AVATAR = {"head": (255, 214, 170), "torso": (40, 170, 230), "arms": (255, 214, 170), "legs": (60, 60, 80)}


@dataclass
class Box:
    x0: float
    x1: float
    y0: float
    y1: float
    z0: float
    z1: float
    color: Tuple[int, int, int]
    glow: bool = False


@dataclass
class Platform:
    box: Box
    cx: float


def build_course(seed: int, length_s: float) -> List[Platform]:
    rng = random.Random(seed)
    plats: List[Platform] = []
    z, y, x = 0.0, 0.0, 0.0
    need = SPEED * (length_s + 6)
    i = 0
    while z < need:
        if i % 12 == 0:
            w, ln, col = 6.0, 6.0, CHECKPOINT
        else:
            w = rng.choice([2.0, 3.0, 4.0, 5.0])
            ln = rng.choice([3.0, 4.0, 6.0, 8.0])
            col = PALETTE[i % len(PALETTE)]
        plats.append(Platform(Box(x - w / 2, x + w / 2, y - 1.2, y, z, z + ln, col), x))
        z += ln + rng.uniform(2.5, 4.5)          # the gap to jump
        y = max(-6.0, min(8.0, y + rng.choice([-1.0, 0.0, 0.0, 1.0, 1.5])))
        x = max(-7.0, min(7.0, x + rng.uniform(-3.0, 3.0)))
        i += 1
    return plats


def decorations(plats: List[Platform], seed: int) -> List[Box]:
    """Thin glowing red 'lava' strips beside some platforms - classic obby danger dressing."""
    rng = random.Random(seed + 1)
    out = []
    for p in plats[1:]:
        b = p.box
        if rng.random() < 0.35 and b.z1 - b.z0 >= 4:
            side = rng.choice([-1, 1])
            x = b.x1 + 0.6 if side > 0 else b.x0 - 1.6
            out.append(Box(x, x + 1.0, b.y1 - 0.4, b.y1 - 0.1, b.z0 + 0.5, b.z1 - 0.5, KILL, glow=True))
    return out


def player_state(plats: List[Platform], t: float) -> Tuple[float, float, float, bool, float]:
    """(x, y_feet, z, airborne, run_phase) at time t, following the course."""
    d = t * SPEED
    for i, p in enumerate(plats[:-1]):
        b, nb = p.box, plats[i + 1].box
        run_start, run_end = b.z0 + 0.6, b.z1 - 0.6
        seg = run_end - run_start
        if d <= seg:
            return p.cx, b.y1, run_start + d, False, t * 9.0
        d -= seg
        jump_len = (nb.z0 + 0.6) - run_end
        if d <= jump_len:
            k = d / jump_len
            apex = max(b.y1, nb.y1) + 2.6
            y = (1 - k) ** 2 * b.y1 + 2 * (1 - k) * k * (2 * apex - (b.y1 + nb.y1) / 2) + k ** 2 * nb.y1
            x = p.cx + (plats[i + 1].cx - p.cx) * (k * k * (3 - 2 * k))
            return x, y, run_end + d, True, t * 9.0
        d -= jump_len
    last = plats[-1]
    return last.cx, last.box.y1, last.box.z0 + 0.6, False, t * 9.0


class Camera:
    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.f = w * 1.05
        self.pitch = math.radians(22)
        self.cx = self.cy = self.cz = 0.0

    def follow(self, px, py, pz, dt):
        k = 1 - math.exp(-dt * 4.0)
        self.cx += (px - self.cx) * k
        self.cy += (py + 7.5 - self.cy) * (1 - math.exp(-dt * 2.5))
        self.cz = pz - 15.0

    def project(self, x, y, z):
        rx, ry, rz = x - self.cx, y - self.cy, z - self.cz
        sp, cp = math.sin(self.pitch), math.cos(self.pitch)
        depth = rz * cp - ry * sp
        up = ry * cp + rz * sp
        if depth < 0.4:
            return None
        return (self.w / 2 + self.f * rx / depth, self.h * 0.34 - self.f * up / depth, depth)


def _fog(c, depth):
    k = min(0.75, max(0.0, (depth - 25) / 140))
    return tuple(int(c[i] + (SKY_BOTTOM[i] - c[i]) * k) for i in range(3))


def _paint(c, a=255):
    return skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(a, *c), Style=skia.Paint.kFill_Style)


_EDGE = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(70, 20, 20, 30), Style=skia.Paint.kStroke_Style, StrokeWidth=2)


def _quad(canvas, cam, pts, color, glow=False):
    proj = [cam.project(*p) for p in pts]
    if any(q is None for q in proj):
        return
    depth = sum(q[2] for q in proj) / 4
    path = skia.Path()
    path.moveTo(proj[0][0], proj[0][1])
    for q in proj[1:]:
        path.lineTo(q[0], q[1])
    path.close()
    canvas.drawPath(path, _paint(_fog(color, depth)))
    if glow:
        canvas.drawPath(path, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(90, 255, 120, 90),
                                         MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 10)))
    elif depth < 60:
        canvas.drawPath(path, _EDGE)


def _shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


def draw_box(canvas, cam, b: Box):
    if cam.cz < b.z0:   # front face
        _quad(canvas, cam, [(b.x0, b.y0, b.z0), (b.x1, b.y0, b.z0), (b.x1, b.y1, b.z0), (b.x0, b.y1, b.z0)], _shade(b.color, 0.80), b.glow)
    if cam.cx < b.x0:   # left side
        _quad(canvas, cam, [(b.x0, b.y0, b.z0), (b.x0, b.y0, b.z1), (b.x0, b.y1, b.z1), (b.x0, b.y1, b.z0)], _shade(b.color, 0.64), b.glow)
    if cam.cx > b.x1:   # right side
        _quad(canvas, cam, [(b.x1, b.y0, b.z0), (b.x1, b.y0, b.z1), (b.x1, b.y1, b.z1), (b.x1, b.y1, b.z0)], _shade(b.color, 0.64), b.glow)
    if cam.cy > b.y1:   # top
        _quad(canvas, cam, [(b.x0, b.y1, b.z0), (b.x1, b.y1, b.z0), (b.x1, b.y1, b.z1), (b.x0, b.y1, b.z1)], _shade(b.color, 1.06), b.glow)


def draw_avatar(canvas, cam, x, y, z, airborne, phase):
    """Blocky avatar seen from behind, drawn in screen space at its projected position."""
    base = cam.project(x, y, z)
    if base is None:
        return
    sx, sy, depth = base
    s = cam.f / depth                      # px per stud at the avatar
    swing = 0.0 if airborne else math.sin(phase)
    shadow_y = cam.project(x, y, z)
    canvas.drawOval(skia.Rect(sx - 1.1 * s, shadow_y[1] - 0.25 * s, sx + 1.1 * s, shadow_y[1] + 0.25 * s), _paint((0, 0, 0), 60))

    def rect(cx, top, w, h, col):
        r = skia.Rect(cx - w / 2 * s, sy - top * s, cx + w / 2 * s, sy - (top - h) * s)
        canvas.drawRect(r, _paint(col))
        canvas.drawRect(r, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(110, 15, 15, 25), Style=skia.Paint.kStroke_Style, StrokeWidth=max(1.5, 0.06 * s)))

    tuck = 0.35 if airborne else 0.0
    for side in (-1, 1):                   # legs: the forward-swinging leg looks shorter from behind
        lift = (0.25 * max(0.0, side * swing)) + tuck
        rect(sx + side * 0.5 * s, 2.0 - lift, 0.95, 2.0 - lift, AVATAR["legs"])
    rect(sx, 4.0, 2.0, 2.0, AVATAR["torso"])
    for side in (-1, 1):
        raise_ = 0.9 if airborne else 0.25 * max(0.0, -side * swing)
        rect(sx + side * 1.5 * s, 4.0 + raise_, 0.95, 2.0, AVATAR["arms"])
    rect(sx, 5.25, 1.25, 1.25, AVATAR["head"])


def _sky(w, h) -> "skia.Image":
    s = skia.Surface(w, h)
    c = s.getCanvas()
    shader = skia.GradientShader.MakeLinear([(0, 0), (0, h)], [skia.ColorSetARGB(255, *SKY_TOP), skia.ColorSetARGB(255, *SKY_BOTTOM)])
    c.drawRect(skia.Rect(0, 0, w, h), skia.Paint(Shader=shader))
    return s.makeImageSnapshot()


def _clouds(canvas, w, h, t, seed):
    rng = random.Random(seed + 7)
    for _ in range(7):
        x0, y0, sc, sp = rng.random(), rng.uniform(0.04, 0.32), rng.uniform(0.6, 1.4), rng.uniform(4, 14)
        x = ((x0 * (w + 600) - t * sp) % (w + 600)) - 300
        y = y0 * h
        for dx, dy, bw, bh in ((0, 0, 220, 70), (60, -40, 140, 60), (-70, -20, 120, 50)):
            canvas.drawRect(skia.Rect(x + dx * sc, y + dy * sc, x + (dx + bw) * sc, y + (dy + bh) * sc), _paint((255, 255, 255), 215))


def frames(duration: float, w: int, h: int, fps: int, seed: int = 0) -> Iterator[np.ndarray]:
    plats = build_course(seed, duration)
    deco = decorations(plats, seed)
    boxes = [p.box for p in plats] + deco
    cam = Camera(w, h)
    px, py, pz, _, _ = player_state(plats, 0.0)
    cam.cx, cam.cy = px, py + 7.5
    sky = _sky(w, h)
    surface = skia.Surface(w, h)
    canvas = surface.getCanvas()
    info = skia.ImageInfo.Make(w, h, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    buf = np.zeros((h, w, 4), np.uint8)
    n = max(1, int(round(duration * fps)))
    for i in range(n):
        t = i / fps
        px, py, pz, air, ph = player_state(plats, t)
        cam.follow(px, py, pz, 1.0 / fps)
        canvas.drawImage(sky, 0, 0)
        _clouds(canvas, w, h, t, seed)
        visible = [b for b in boxes if b.z1 > cam.cz + 0.5 and b.z0 < cam.cz + 190]
        ahead = sorted([b for b in visible if b.z1 >= pz], key=lambda b: -b.z0)
        behind = sorted([b for b in visible if b.z1 < pz], key=lambda b: -b.z0)
        for b in ahead:
            draw_box(canvas, cam, b)
        draw_avatar(canvas, cam, px, py, pz, air, ph)
        for b in behind:
            draw_box(canvas, cam, b)
        surface.readPixels(info, buf, w * 4, 0, 0)
        yield buf
