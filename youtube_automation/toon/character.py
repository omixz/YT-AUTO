"""A rigged cartoon character: front-view puppet with a skeleton (2-bone arms and
legs), blinking eyes, a mouth driven by narration loudness, and costume pieces
(headwear, prop) taken from the existing archetype table.

Units: the figure is ~100 units tall standing on y=0 (feet), y grows downward.
`scale` converts units to pixels. Joint angles are degrees measured from
"straight down"; positive swings outward/forward.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import skia

from . import art
from .art import INK, Color, fill, inked, inked_circle, inked_oval, limb, poly_path, shade, stroke
from .easing import clamp01, ease_in_out, ease_out_back, wobble

SKIN_TONES = [(247, 214, 183), (234, 185, 142), (205, 152, 108), (160, 108, 72), (115, 77, 52)]
HAIR_COLORS = [(40, 30, 28), (86, 58, 36), (120, 76, 42), (150, 110, 60), (190, 120, 56), (214, 190, 120)]
_BEARDED = {"viking", "norse", "odin", "thor", "scholar", "pharaoh", "caesar", "priest", "pirate", "general"}
_SWORDS = {"sword", "gladius", "katana", "cutlass", "khopesh", "obsidian_sword", "macuahuitl", "dagger"}
_STAFFS = {"staff", "crook_flail", "vine_staff", "spear", "trident"}


@dataclass
class Look:
    skin: Color = SKIN_TONES[1]
    hair: Color = HAIR_COLORS[1]
    outfit: Color = (90, 90, 130)
    trousers: Color = (60, 60, 85)
    headwear: Optional[str] = None
    prop: Optional[str] = None
    beard: bool = False
    hood: bool = False
    horned: bool = False
    # --- variety: body, hair, face, clothing style
    build: float = 1.0          # torso/limb width multiplier (slim .85 .. stocky 1.25)
    height: float = 1.0         # overall size multiplier
    hair_style: str = "short"   # short | bald | long | bun | curly
    facial: str = ""            # "" | mustache | goatee | beard
    glasses: bool = False
    style: str = "shirt"        # shirt | coat | dress | robe | armor | uniform
    female: bool = False

    @classmethod
    def from_archetype(cls, name: str, table: dict, rng: random.Random) -> "Look":
        outfit, headwear, weapon, _pose, _desc = table.get(name, table["scholar"])
        prop = weapon if weapon in (_SWORDS | _STAFFS | {"axe", "hammer", "scroll", "compass"}) else None
        return cls(
            skin=rng.choice(SKIN_TONES), hair=rng.choice(HAIR_COLORS),
            outfit=tuple(outfit), trousers=shade(tuple(outfit), -0.35),
            headwear=headwear, prop=prop,
            beard=name in _BEARDED, hood=(name in {"assassin"}), horned=(name in {"viking", "norse", "thor"}),
            style="armor" if name in {"knight", "templar", "gladiator", "samurai"} else "robe" if name in {"pharaoh", "priest", "scholar"} else "shirt",
        )


@dataclass
class Pose:
    lean: float = 0.0       # torso lean, degrees (+ forward)
    tilt: float = 0.0       # head tilt
    bob: float = 0.0        # vertical offset in units (negative = up)
    sh_r: float = 12.0      # right (prop-side) shoulder angle
    el_r: float = 8.0
    sh_l: float = 12.0
    el_l: float = 8.0
    hip_r: float = 0.0
    kn_r: float = 0.0
    hip_l: float = 0.0
    kn_l: float = 0.0


@dataclass
class Face:
    mood: str = "neutral"   # neutral | shocked | serious
    mouth: float = 0.0      # 0 closed .. 1 wide open
    blink: float = 0.0      # 0 open .. 1 closed
    look_x: float = 0.0     # -1..1 pupil direction


# ---- pose library -------------------------------------------------------------------------

def pose_idle(t: float, seed: float = 0.0) -> Pose:
    br = math.sin(t * 2.2 + seed)
    return Pose(lean=1.2 * wobble(t, seed), bob=-0.6 * br, sh_r=10 + 2 * br, sh_l=10 - 2 * br,
                el_r=6, el_l=6, tilt=2.0 * wobble(t * 0.7, seed + 3))


def pose_talk(t: float, energy: float, seed: float = 0.0) -> Pose:
    """Idle breathing plus a periodic expressive gesture with the prop-side arm."""
    p = pose_idle(t, seed)
    cycle = (t + seed) % 3.2
    g = ease_in_out(clamp01(cycle / 0.5)) * (1 - ease_in_out(clamp01((cycle - 1.6) / 0.6)))
    sway = math.sin(t * 4.0 + seed) * 6 * g
    p.sh_r = 12 + (52 + sway * 0.6) * g
    p.el_r = 8 + (24 + sway * 0.4) * g
    p.bob -= 1.2 * energy
    p.tilt += 3 * energy * math.sin(t * 6 + seed)
    p.lean += 2.0 * g
    return p


def pose_walk(t: float, speed: float = 1.0) -> Pose:
    ph = t * 7.0 * speed
    s = math.sin(ph)
    c = math.cos(ph)
    return Pose(lean=5, bob=-1.6 * abs(c), sh_r=-34 * s + 8, el_r=14, sh_l=34 * s + 8, el_l=14,
                hip_r=30 * s, kn_r=max(0.0, 42 * c), hip_l=-30 * s, kn_l=max(0.0, -42 * c),
                tilt=1.5 * s)


def pose_shock(t: float, since: float) -> Pose:
    """Startled recoil: a hop back with both arms flung up, trembling."""
    k = ease_out_back(clamp01(since / 0.28))
    jitter = math.sin(t * 38) * 1.6 * clamp01(1.4 - since)
    return Pose(lean=-10 * k + jitter, bob=-9 * math.sin(clamp01(since / 0.5) * math.pi), tilt=-5 * k,
                sh_r=150 * k, el_r=20, sh_l=150 * k, el_l=20,
                hip_r=-6 * k, kn_r=8 * k, hip_l=10 * k, kn_l=4 * k)


def pose_fight(t: float, phase: float) -> Pose:
    """Repeating swing: wind-up, strike, recover."""
    cyc = ((t + phase) % 1.1) / 1.1
    if cyc < 0.35:
        k = ease_in_out(cyc / 0.35)
        r = 70 + 90 * k           # wind up (arm rising)
        lean = -6 * k
    elif cyc < 0.5:
        k = ease_in_out((cyc - 0.35) / 0.15)
        r = 160 - 150 * k         # fast downward strike
        lean = -6 + 18 * k
    else:
        k = ease_in_out((cyc - 0.5) / 0.5)
        r = 10 + 60 * k
        lean = 12 - 12 * k
    return Pose(lean=lean, bob=-1.2 * math.sin(t * 9 + phase), sh_r=r, el_r=25, sh_l=30, el_l=40,
                hip_r=18, kn_r=10, hip_l=-14, kn_l=6)


# ---- drawing --------------------------------------------------------------------------------

def _dir(angle_deg: float) -> Tuple[float, float]:
    a = math.radians(angle_deg)
    return math.sin(a), math.cos(a)


def draw_shadow(canvas, x, y, scale, w=1.0, a=70):
    rect = skia.Rect(x - 26 * scale * w, y - 4 * scale, x + 26 * scale * w, y + 5 * scale)
    canvas.drawOval(rect, fill((0, 0, 0), a))


def draw_character(canvas, look: Look, pose: Pose, face: Face, x: float, y: float, scale: float,
                   facing: int = 1) -> None:
    u = scale * look.height
    f = facing
    o = max(2.0, 2.6 * u)  # outline width in px
    bd = look.build
    tw_s, tw_h = 15 * bd, 11 * bd

    def X(px):  # local x (forward +) -> screen x
        return x + f * px * u

    def Y(py):
        return y + py * u

    hip_y = -34 + pose.bob
    lean = math.radians(pose.lean)
    sx, sy = 0 + math.sin(lean) * 30, hip_y - math.cos(lean) * 30
    head = (sx + math.sin(lean) * 3, sy - 21)

    # --- legs
    for side, hp, kn in ((-1, pose.hip_l, pose.kn_l), (1, pose.hip_r, pose.kn_r)):
        hx = side * 8 * bd
        dx, dy = _dir(hp)
        kx, ky = hx + 17 * dx, hip_y + 17 * dy
        dx2, dy2 = _dir(hp - kn)
        ax, ay = kx + 17 * dx2, ky + 17 * dy2
        limb(canvas, [(X(hx), Y(hip_y)), (X(kx), Y(ky)), (X(ax), Y(ay))], 9 * u * bd, look.trousers, o)
        if look.style == "uniform":   # tall boots
            limb(canvas, [(X(kx), Y(ky)), (X(ax), Y(ay))], 9.6 * u * bd, (46, 36, 30), o)
        shoe = skia.Rect(min(X(ax) - 6 * u, X(ax + 9) ), Y(ay) - 4 * u, max(X(ax) + 6 * u, X(ax + 9)), Y(ay) + 3 * u)
        canvas.drawRRect(skia.RRect.MakeRectXY(shoe, 3 * u, 3 * u), fill((50, 38, 34)))
        canvas.drawRRect(skia.RRect.MakeRectXY(shoe, 3 * u, 3 * u), stroke(INK, o))

    # --- lower garments drawn over the legs (dress / robe / coat tails)
    if look.style in {"dress", "robe", "coat"}:
        hem = {"dress": -13, "robe": -5, "coat": -17}[look.style]
        flare = {"dress": 21, "robe": 19, "coat": 16}[look.style] * bd
        skirt = skia.Path()
        skirt.moveTo(X(-tw_h), Y(hip_y - 2))
        skirt.lineTo(X(tw_h), Y(hip_y - 2))
        skirt.quadTo(X(flare * 0.9), Y((hip_y + hem) / 2), X(flare), Y(hem))
        skirt.quadTo(X(0), Y(hem + 3), X(-flare), Y(hem))
        skirt.quadTo(X(-flare * 0.9), Y((hip_y + hem) / 2), X(-tw_h), Y(hip_y - 2))
        skirt.close()
        inked(canvas, skirt, look.outfit if look.style != "coat" else shade(look.outfit, -0.12), o)

    # --- torso
    ux, uy = math.cos(lean), math.sin(lean)  # shoulder-line direction
    s_l = (sx - tw_s * ux, sy - tw_s * uy * 0.3)
    s_r = (sx + tw_s * ux, sy + tw_s * uy * 0.3)
    torso = skia.Path()
    torso.moveTo(X(s_l[0]), Y(s_l[1]))
    torso.quadTo(X(sx), Y(sy - 4), X(s_r[0]), Y(s_r[1]))
    torso.lineTo(X(tw_h), Y(hip_y + 3))
    torso.quadTo(X(0), Y(hip_y + 7), X(-tw_h), Y(hip_y + 3))
    torso.close()
    inked(canvas, torso, look.outfit, o)
    if look.style == "armor":   # pauldrons + chest plate line
        for sd in (-1, 1):
            inked_circle(canvas, X(sx + sd * tw_s), Y(sy + 1), 7.5 * u, shade(look.outfit, 0.08), o)
        canvas.drawLine(X(sx), Y(sy + 4), X(sx), Y(hip_y + 2), stroke(shade(look.outfit, -0.4), 2.2 * u))
    elif look.style == "uniform":   # buttons + breast pockets
        for k in range(3):
            canvas.drawCircle(X(sx), Y(sy + 6 + k * 7), 1.3 * u, fill((226, 196, 90)))
        for sd in (-1, 1):
            canvas.drawRect(skia.Rect(X(sx + sd * 9) - 2.6 * u, Y(sy + 6), X(sx + sd * 9) + 2.6 * u, Y(sy + 12)), stroke(shade(look.outfit, -0.4), 1.2 * u))
    # belt + collar detail
    canvas.drawLine(X(-tw_h + 1), Y(hip_y + 1), X(tw_h - 1), Y(hip_y + 1), stroke(shade(look.outfit, -0.5), 3.2 * u))
    canvas.drawPath(poly_path([(X(sx - 5), Y(sy - 1)), (X(sx), Y(sy + 7)), (X(sx + 5), Y(sy - 1))], close=False),
                    stroke(shade(look.outfit, -0.45), 2.2 * u))

    # --- arms (drawn after torso so they read in front)
    hands = {}
    for side, sh, el in ((-1, pose.sh_l, pose.el_l), (1, pose.sh_r, pose.el_r)):
        base = (s_r if side == 1 else s_l)
        bx, by = base[0] + side * -1.0, base[1] + 2
        d1 = _dir(sh)
        ex, ey = bx + side * 17 * d1[0], by + 17 * d1[1]
        d2 = _dir(sh + el)
        hx, hy = ex + side * 15 * d2[0], ey + 15 * d2[1]
        limb(canvas, [(X(bx), Y(by)), (X(ex), Y(ey))], 7.5 * u * bd, look.outfit, o)
        limb(canvas, [(X(ex), Y(ey)), (X(hx), Y(hy))], 6.2 * u, look.skin, o)
        inked_circle(canvas, X(hx), Y(hy), 4.4 * u, look.skin, o)
        hands[side] = (hx, hy, side * d2[0], d2[1])

    # --- prop in the right hand
    if look.prop:
        hx, hy, dx, dy = hands[1]
        _draw_prop(canvas, look.prop, X(hx), Y(hy), f * dx, dy, u, o)

    # --- head
    hx_, hy_ = head
    cx, cy = X(hx_), Y(hy_)
    r = 19 * u
    if look.hood:
        cloak = skia.Path()
        cloak.addOval(skia.Rect(cx - r * 1.28, cy - r * 1.3, cx + r * 1.28, cy + r * 1.22))
        inked(canvas, cloak, (38, 36, 48), o)
    canvas.save()
    canvas.translate(cx, cy)
    canvas.rotate(pose.tilt * f)
    canvas.translate(-cx, -cy)
    inked_circle(canvas, cx - f * 0.0, cy, r, look.skin, o)
    for sd in (-1, 1):
        inked_circle(canvas, cx + sd * r * 0.98, cy + 1.5 * u, 3.6 * u, look.skin, o * 0.8)
    if not look.hood:
        _draw_hair(canvas, look, cx, cy, r, o)
    if look.beard or look.facial == "beard":
        b = skia.Path()
        b.moveTo(cx - r * 0.97, cy + r * 0.28)
        b.quadTo(cx - r * 1.0, cy + r * 1.28, cx, cy + r * 1.42)
        b.quadTo(cx + r * 1.0, cy + r * 1.28, cx + r * 0.97, cy + r * 0.28)
        b.quadTo(cx + r * 0.7, cy + r * 0.86, cx, cy + r * 0.84)
        b.quadTo(cx - r * 0.7, cy + r * 0.86, cx - r * 0.97, cy + r * 0.28)
        inked(canvas, b, look.hair, o * 0.9)
    _draw_face(canvas, face, look, cx, cy, r, u, o, f)
    if look.facial == "mustache":
        for sd in (-1, 1):
            m = skia.Path()
            m.moveTo(cx, cy + r * 0.44)
            m.quadTo(cx + sd * r * 0.28, cy + r * 0.36, cx + sd * r * 0.5, cy + r * 0.5)
            m.quadTo(cx + sd * r * 0.28, cy + r * 0.52, cx, cy + r * 0.5)
            inked(canvas, m, look.hair, o * 0.5)
    elif look.facial == "goatee":
        inked(canvas, poly_path([(cx - 5 * u, cy + r * 0.78), (cx + 5 * u, cy + r * 0.78), (cx, cy + r * 1.12)]), look.hair, o * 0.6)
    if look.glasses:
        for sd in (-1, 1):
            canvas.drawCircle(cx + sd * r * 0.38, cy + r * 0.02, 7.6 * u, stroke(INK, 2.0 * u))
        canvas.drawLine(cx - r * 0.38 + 7.6 * u, cy + r * 0.02, cx + r * 0.38 - 7.6 * u, cy + r * 0.02, stroke(INK, 2.0 * u))
    _draw_headwear(canvas, look, cx, cy, r, u, o)
    canvas.restore()


_HAIR_HIDING = {"helmet", "hat", "cap", "kepi", "brodie", "stahlhelm", "pickelhaube", "adrian", "peaked", "beret",
                "flatcap", "tophat", "tricorn", "turban"}


def _draw_hair(canvas, look, cx, cy, r, o):
    if look.headwear in _HAIR_HIDING or look.hair_style == "bald":
        return
    if look.hair_style == "long" or look.female:
        for sd in (-1, 1):
            cur = skia.Path()
            cur.moveTo(cx + sd * r * 0.9, cy - r * 0.3)
            cur.cubicTo(cx + sd * r * 1.3, cy + r * 0.2, cx + sd * r * 1.25, cy + r * 1.1, cx + sd * r * 0.9, cy + r * 1.55)
            cur.lineTo(cx + sd * r * 0.6, cy + r * 1.4)
            cur.cubicTo(cx + sd * r * 0.8, cy + r * 0.8, cx + sd * r * 0.8, cy + r * 0.2, cx + sd * r * 0.7, cy - r * 0.2)
            cur.close()
            inked(canvas, cur, look.hair, o * 0.9)
    p = skia.Path()
    p.moveTo(cx - r * 1.0, cy - r * 0.05)
    p.cubicTo(cx - r * 1.15, cy - r * 1.25, cx + r * 1.15, cy - r * 1.25, cx + r * 1.0, cy - r * 0.05)
    p.quadTo(cx + r * 0.55, cy - r * 0.62, cx, cy - r * 0.55)
    p.quadTo(cx - r * 0.55, cy - r * 0.62, cx - r * 1.0, cy - r * 0.05)
    inked(canvas, p, look.hair, o * 0.9)
    if look.hair_style == "bun":
        inked_circle(canvas, cx, cy - r * 1.18, r * 0.34, look.hair, o * 0.9)
    elif look.hair_style == "curly":
        for k in range(-3, 4):
            inked_circle(canvas, cx + k * r * 0.3, cy - r * (0.95 - 0.07 * abs(k)), r * 0.3, look.hair, o * 0.8)


def _draw_face(canvas, face: Face, look: Look, cx, cy, r, u, o, f):
    ex = r * 0.38
    ey = cy + r * 0.02
    mood = face.mood
    wide = 1.0 + (0.35 if mood == "shocked" else 0)
    lid = clamp01(face.blink)
    for sd in (-1, 1):
        px = cx + sd * ex
        rx, ry = 5.0 * u * wide, 6.0 * u * wide * (1 - 0.88 * lid)
        rect = skia.Rect(px - rx, ey - ry, px + rx, ey + ry)
        canvas.drawOval(rect, fill((255, 255, 255)))
        canvas.drawOval(rect, stroke(INK, o * 0.75))
        if lid < 0.6:
            pr = (2.6 if mood != "shocked" else 1.7) * u
            canvas.drawCircle(px + face.look_x * 1.8 * u, ey + 0.6 * u, pr, fill(INK))
            canvas.drawCircle(px + face.look_x * 1.8 * u - 0.8 * u, ey - 0.6 * u, 0.9 * u, fill((255, 255, 255)))
        by = ey - ry - 3.4 * u
        if mood == "serious":
            a, b = (by + 3.2 * u, by - 1.2 * u) if sd < 0 else (by - 1.2 * u, by + 3.2 * u)
        elif mood == "shocked":
            a, b = by - 3.0 * u, by - 4.5 * u
            if sd > 0:
                a, b = b, a
        else:
            a, b = by + 0.6 * u, by - 0.6 * u
            if sd > 0:
                a, b = b, a
        canvas.drawLine(px - 5.6 * u, a, px + 5.6 * u, b, stroke(look.hair if look.hair else INK, 2.4 * u))
    if look.female:
        for sd in (-1, 1):
            canvas.drawLine(cx + sd * ex + sd * 4.6 * u, ey - 3.6 * u, cx + sd * ex + sd * 7.6 * u, ey - 6.0 * u, stroke(INK, 1.8 * u))
    # nose
    canvas.drawPath(poly_path([(cx, cy + r * 0.08), (cx - 2.4 * u, cy + r * 0.34), (cx + 2.4 * u, cy + r * 0.34)], close=False),
                    stroke(shade(look.skin, -0.28), 1.8 * u))
    # mouth
    my = cy + r * 0.58
    m = clamp01(face.mouth)
    if mood == "shocked":
        m = max(m, 0.75)
    if m < 0.12:
        d = 2.2 * u if mood != "serious" else -1.2 * u
        pth = skia.Path()
        pth.moveTo(cx - 5.5 * u, my)
        pth.quadTo(cx, my + d, cx + 5.5 * u, my)
        canvas.drawPath(pth, stroke(INK, 2.2 * u))
    else:
        mw = (4.6 + 3.0 * m) * u
        mh = (1.8 + 6.5 * m) * u
        rect = skia.Rect(cx - mw, my - mh * 0.35, cx + mw, my + mh)
        canvas.drawOval(rect, fill((92, 28, 40)))
        if m > 0.4:
            canvas.drawOval(skia.Rect(cx - mw * 0.55, my + mh * 0.35, cx + mw * 0.55, my + mh * 0.95), fill((214, 96, 104)))
        canvas.drawOval(rect, stroke(INK, 2.0 * u))


def _draw_headwear(canvas, look: Look, cx, cy, r, u, o):
    hw = look.headwear
    if hw == "crown":
        top = cy - r * 0.95
        pts = [(cx - r * 0.8, top + 2 * u), (cx - r * 0.8, top - 10 * u), (cx - r * 0.4, top - 3 * u),
               (cx, top - 13 * u), (cx + r * 0.4, top - 3 * u), (cx + r * 0.8, top - 10 * u), (cx + r * 0.8, top + 2 * u)]
        inked(canvas, poly_path(pts), (245, 200, 66), o * 0.9)
        inked_circle(canvas, cx, top - 5 * u, 2.2 * u, (200, 50, 70), o * 0.5)
    elif hw == "helmet":
        dome = skia.Path()
        dome.moveTo(cx - r * 1.05, cy - r * 0.1)
        dome.cubicTo(cx - r * 1.1, cy - r * 1.45, cx + r * 1.1, cy - r * 1.45, cx + r * 1.05, cy - r * 0.1)
        dome.close()
        inked(canvas, dome, (150, 156, 168), o)
        canvas.drawLine(cx - r * 1.1, cy - r * 0.1, cx + r * 1.1, cy - r * 0.1, stroke(INK, o * 1.3))
        canvas.drawRect(skia.Rect(cx - 2 * u, cy - r * 0.1, cx + 2 * u, cy + r * 0.45), fill((130, 136, 148)))
        for sd in ((-1, 1) if look.horned else ()):
            hornp = skia.Path()
            hornp.moveTo(cx + sd * r * 0.95, cy - r * 0.55)
            hornp.quadTo(cx + sd * r * 1.55, cy - r * 0.75, cx + sd * r * 1.35, cy - r * 1.35)
            hornp.quadTo(cx + sd * r * 1.25, cy - r * 0.85, cx + sd * r * 0.85, cy - r * 0.8)
            inked(canvas, hornp, (236, 228, 205), o * 0.7)
    elif hw == "hat":
        inked_oval(canvas, cx, cy - r * 0.55, r * 1.45, r * 0.3, (80, 62, 48), o)
        pts = [(cx - r * 0.78, cy - r * 0.6), (cx - r * 0.6, cy - r * 1.35), (cx + r * 0.6, cy - r * 1.35), (cx + r * 0.78, cy - r * 0.6)]
        inked(canvas, poly_path(pts), (96, 74, 56), o)
        canvas.drawLine(cx - r * 0.76, cy - r * 0.78, cx + r * 0.76, cy - r * 0.78, stroke((40, 30, 28), 3.2 * u))
    elif hw in {"kepi", "peaked"}:
        col_ = look.outfit if hw == "kepi" else shade(look.outfit, -0.15)
        inked(canvas, poly_path([(cx - r * 0.95, cy - r * 0.34), (cx - r * 0.85, cy - r * 1.18), (cx + r * 0.85, cy - r * 1.18), (cx + r * 0.95, cy - r * 0.34)]), col_, o)
        canvas.drawRect(skia.Rect(cx - r * 0.95, cy - r * 0.5, cx + r * 0.95, cy - r * 0.36), fill((236, 220, 130) if hw == "peaked" else shade(col_, -0.35)))
        canvas.drawRRect(skia.RRect.MakeRectXY(skia.Rect(cx - r * 0.2, cy - r * 0.38, cx + r * 1.2, cy - r * 0.22), 3 * u, 3 * u), fill((40, 34, 30)))
    elif hw in {"brodie", "stahlhelm", "adrian", "pickelhaube"}:
        tin = {"brodie": (112, 118, 92), "stahlhelm": (86, 92, 90), "adrian": (96, 120, 160), "pickelhaube": (176, 160, 110)}[hw]
        dome = skia.Path()
        dome.moveTo(cx - r * 1.12, cy - r * 0.18)
        dome.cubicTo(cx - r * 1.1, cy - r * 1.4, cx + r * 1.1, cy - r * 1.4, cx + r * 1.12, cy - r * 0.18)
        if hw == "stahlhelm":
            dome.lineTo(cx + r * 1.0, cy + r * 0.3)
            dome.lineTo(cx - r * 1.0, cy + r * 0.3)
        dome.close()
        inked(canvas, dome, tin, o)
        if hw == "adrian":
            canvas.drawLine(cx, cy - r * 1.28, cx, cy - r * 0.45, stroke(shade(tin, -0.3), 3 * u))
        if hw == "pickelhaube":
            inked(canvas, poly_path([(cx - 2.5 * u, cy - r * 1.18), (cx, cy - r * 1.55), (cx + 2.5 * u, cy - r * 1.18)]), (230, 210, 120), o * 0.6)
    elif hw == "beret":
        inked_oval(canvas, cx + r * 0.1, cy - r * 0.78, r * 1.05, r * 0.38, look.outfit, o)
    elif hw in {"flatcap", "tophat", "tricorn"}:
        if hw == "tophat":
            inked(canvas, poly_path([(cx - r * 0.62, cy - r * 0.6), (cx - r * 0.55, cy - r * 1.75), (cx + r * 0.55, cy - r * 1.75), (cx + r * 0.62, cy - r * 0.6)]), (34, 32, 40), o)
            inked_oval(canvas, cx, cy - r * 0.58, r * 1.2, r * 0.2, (34, 32, 40), o)
        elif hw == "tricorn":
            inked(canvas, poly_path([(cx - r * 1.35, cy - r * 0.5), (cx, cy - r * 1.35), (cx + r * 1.35, cy - r * 0.5), (cx, cy - r * 0.35)]), (44, 40, 52), o)
        else:
            inked_oval(canvas, cx, cy - r * 0.7, r * 1.05, r * 0.42, shade(look.outfit, -0.2), o)
            canvas.drawRRect(skia.RRect.MakeRectXY(skia.Rect(cx + r * 0.1, cy - r * 0.55, cx + r * 1.25, cy - r * 0.4), 3 * u, 3 * u), fill(shade(look.outfit, -0.45)))
    elif hw == "turban":
        inked_oval(canvas, cx, cy - r * 0.78, r * 1.12, r * 0.62, (236, 226, 206), o)
        canvas.drawArc(skia.Rect(cx - r * 0.8, cy - r * 1.2, cx + r * 0.8, cy - r * 0.4), 200, 120, False, stroke(shade((236, 226, 206), -0.25), 2.2 * u))
    elif hw == "cap":
        dome = skia.Path()
        dome.moveTo(cx - r * 1.0, cy - r * 0.32)
        dome.cubicTo(cx - r * 1.0, cy - r * 1.3, cx + r * 1.0, cy - r * 1.3, cx + r * 1.0, cy - r * 0.32)
        dome.close()
        inked(canvas, dome, shade(look.outfit, -0.1), o)
        canvas.drawRRect(skia.RRect.MakeRectXY(skia.Rect(cx - r * 0.2, cy - r * 0.42, cx + r * 1.25, cy - r * 0.24), 3 * u, 3 * u), fill(shade(look.outfit, -0.35)))


def _draw_prop(canvas, prop: str, hx, hy, dx, dy, u, o):
    """Prop pointing along (dx, dy) from the hand."""
    if prop in _STAFFS:
        dx, dy = 0.10 * (1 if dx >= 0 else -1), -1.0   # upright, slight cant
    n = math.hypot(dx, dy) or 1.0
    dx, dy = dx / n, dy / n
    px, py = -dy, dx

    def at(a, b):
        return (hx + dx * a * u + px * b * u, hy + dy * a * u + py * b * u)

    if prop in _SWORDS:
        L = 30 if prop == "dagger" else 44
        inked(canvas, poly_path([at(2, -2.2), at(L, -2.2), at(L + 7, 0), at(L, 2.2), at(2, 2.2)]), (215, 222, 232), o * 0.8)
        canvas.drawLine(*at(2, -6.5), *at(2, 6.5), stroke(INK, 3.6 * u))
        canvas.drawLine(*at(2, -6.5), *at(2, 6.5), stroke((200, 160, 60), 2.0 * u))
    elif prop in _STAFFS:
        canvas.drawLine(*at(-30, 0), *at(52, 0), stroke(INK, 5.4 * u))
        canvas.drawLine(*at(-30, 0), *at(52, 0), stroke((126, 90, 58), 3.2 * u))
        if prop in {"spear", "trident"}:
            inked(canvas, poly_path([at(50, -4), at(66, 0), at(50, 4)]), (215, 222, 232), o * 0.7)
        else:
            inked_circle(canvas, *at(54, 0), 4.2 * u, (240, 200, 80), o * 0.6)
    elif prop == "axe":
        canvas.drawLine(*at(-10, 0), *at(36, 0), stroke(INK, 5.2 * u))
        canvas.drawLine(*at(-10, 0), *at(36, 0), stroke((126, 90, 58), 3.0 * u))
        inked(canvas, poly_path([at(28, 0), at(36, -14), at(44, -10), at(42, 10), at(36, 14)]), (170, 176, 188), o * 0.8)
    elif prop == "hammer":
        canvas.drawLine(*at(-10, 0), *at(38, 0), stroke(INK, 5.2 * u))
        canvas.drawLine(*at(-10, 0), *at(38, 0), stroke((126, 90, 58), 3.0 * u))
        inked(canvas, poly_path([at(34, -10), at(52, -10), at(52, 10), at(34, 10)]), (130, 136, 150), o * 0.8)
    elif prop == "scroll":
        inked(canvas, poly_path([at(2, -6), at(26, -6), at(26, 6), at(2, 6)]), (240, 226, 188), o * 0.8)
        for a in (2, 26):
            inked_oval(canvas, *at(a, 0), 3.2 * u, 7.4 * u, (214, 190, 140), o * 0.8)
        for k in (-3, 0, 3):
            canvas.drawLine(*at(7, k), *at(21, k), stroke((120, 96, 70), 1.0 * u))
    elif prop == "compass":
        inked_circle(canvas, *at(8, 0), 7 * u, (222, 190, 90), o * 0.8)
        canvas.drawLine(*at(8, 0), *at(13, -3), stroke((190, 40, 50), 1.6 * u))
