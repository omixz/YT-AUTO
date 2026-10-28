"""Cartoon effects: emote bubbles, impact bursts, speed lines, and a recurring
sidekick mascot. All cheap vector drawing - this is what makes a scene feel
*alive* rather than a talking puppet."""
from __future__ import annotations

import math
from typing import Tuple

import skia

from .art import INK, Color, fill, glow, inked, inked_circle, inked_oval, poly_path, shade, stroke
from .easing import clamp01, ease_in_out, ease_out_back, wobble


def pop_scale(since: float, dur: float = 0.35) -> float:
    """Spring-in scale for something that appeared `since` seconds ago (0 before it appears)."""
    if since < 0:
        return 0.0
    return ease_out_back(clamp01(since / dur))


def draw_emote(canvas, kind: str, x: float, y: float, u: float, since: float, life: float = 1.6) -> None:
    """Classic cartoon thought-symbols floating over a head: '!', '?', sweat, bulb, sparkle, anger."""
    if since < 0 or since > life:
        return
    k = pop_scale(since) * (1 - ease_in_out(clamp01((since - (life - 0.3)) / 0.3)))
    if k <= 0:
        return
    bob = math.sin(since * 9) * 1.4 * u
    canvas.save()
    canvas.translate(x, y + bob)
    canvas.scale(k, k)
    o = max(2.0, 2.4 * u)
    if kind == "!":
        inked(canvas, poly_path([(-5 * u, -22 * u), (5 * u, -22 * u), (3 * u, -5 * u), (-3 * u, -5 * u)]), (232, 56, 56), o)
        inked_circle(canvas, 0, 1 * u, 3.4 * u, (232, 56, 56), o)
    elif kind == "?":
        p = skia.Path()
        p.moveTo(-6 * u, -17 * u)
        p.cubicTo(-6 * u, -27 * u, 8 * u, -27 * u, 8 * u, -18 * u)
        p.cubicTo(8 * u, -11 * u, 0, -12 * u, 0, -5 * u)
        canvas.drawPath(p, stroke(INK, 8.5 * u))
        canvas.drawPath(p, stroke((250, 200, 50), 5 * u))
        inked_circle(canvas, 0, 1.5 * u, 3.2 * u, (250, 200, 50), o)
    elif kind == "sweat":
        d = skia.Path()
        d.moveTo(0, -16 * u)
        d.cubicTo(8 * u, -4 * u, 7 * u, 4 * u, 0, 4 * u)
        d.cubicTo(-7 * u, 4 * u, -8 * u, -4 * u, 0, -16 * u)
        inked(canvas, d, (130, 200, 245), o)
    elif kind == "bulb":
        inked_circle(canvas, 0, -14 * u, 9 * u, (255, 230, 90), o)
        canvas.drawRect(skia.Rect(-4 * u, -6 * u, 4 * u, 0), fill((150, 150, 160)))
        canvas.drawRect(skia.Rect(-4 * u, -6 * u, 4 * u, 0), stroke(INK, o * 0.8))
        glow(canvas, 0, -14 * u, 26 * u, (255, 230, 90), 150)
        for a in range(-60, 61, 30):
            ar = math.radians(a - 90)
            canvas.drawLine(math.cos(ar) * 13 * u, -14 * u + math.sin(ar) * 13 * u,
                            math.cos(ar) * 19 * u, -14 * u + math.sin(ar) * 19 * u, stroke(INK, 2.4 * u))
    elif kind == "sparkle":
        for sx, sy, r in ((0, -14, 8), (-12, -4, 5), (11, -6, 4)):
            star = [(0, -r), (r * 0.28, -r * 0.28), (r, 0), (r * 0.28, r * 0.28), (0, r), (-r * 0.28, r * 0.28), (-r, 0), (-r * 0.28, -r * 0.28)]
            canvas.save()
            canvas.translate(sx * u, sy * u)
            canvas.rotate(since * 90)
            inked(canvas, poly_path([(a * u, b * u) for a, b in star]), (255, 224, 90), o * 0.7)
            canvas.restore()
    elif kind == "anger":
        for sgn in (1, -1):
            canvas.drawLine(-7 * u, -12 * u * sgn - 8 * u, 7 * u, -12 * u * sgn - 8 * u, stroke(INK, 0))
        canvas.drawPath(poly_path([(-9 * u, -20 * u), (-3 * u, -14 * u), (-9 * u, -8 * u)], close=False), stroke((220, 40, 40), 3.4 * u))
        canvas.drawPath(poly_path([(9 * u, -20 * u), (3 * u, -14 * u), (9 * u, -8 * u)], close=False), stroke((220, 40, 40), 3.4 * u))
    canvas.restore()


def draw_burst(canvas, x: float, y: float, u: float, since: float, dur: float = 0.32,
               c: Color = (255, 214, 64)) -> None:
    """A comic impact star that pops and fades - used on every sword hit and reveal."""
    if since < 0 or since > dur:
        return
    k = since / dur
    r_out = (18 + 34 * ease_out_back(clamp01(k * 1.6))) * u
    r_in = r_out * 0.52
    pts = []
    for i in range(16):
        a = i * math.pi / 8 + 0.2
        r = r_out if i % 2 == 0 else r_in
        pts.append((x + math.cos(a) * r, y + math.sin(a) * r))
    alpha = int(255 * (1 - clamp01((k - 0.55) / 0.45)))
    canvas.drawPath(poly_path(pts), fill(c, alpha))
    canvas.drawPath(poly_path(pts), stroke(INK, max(2.0, 2.6 * u), alpha))
    inner = [(x + (px - x) * 0.45, y + (py - y) * 0.45) for px, py in pts]
    canvas.drawPath(poly_path(inner), fill((255, 250, 220), alpha))


def draw_speed_lines(canvas, w: int, h: int, since: float, dur: float = 0.5, a: int = 150) -> None:
    """Radial 'manga' lines closing in from the frame edge - the reveal/shock punctuation."""
    if since < 0 or since > dur:
        return
    k = since / dur
    alpha = int(a * (1 - ease_in_out(k)))
    cx, cy = w / 2, h / 2
    reach = math.hypot(w, h) / 2
    p = stroke((255, 255, 255), max(2.0, w / 480), alpha)
    for i in range(34):
        ang = i * (math.pi * 2 / 34) + math.sin(i * 12.9898) * 0.05
        r0 = reach * (0.55 + 0.2 * ((i * 7) % 5) / 5 + 0.25 * k)
        canvas.drawLine(cx + math.cos(ang) * r0, cy + math.sin(ang) * r0,
                        cx + math.cos(ang) * reach * 1.1, cy + math.sin(ang) * reach * 1.1, p)


def draw_cta_card(canvas, cx: float, cy: float, u: float, since: float, hold: float = 3.4, final: bool = False) -> None:
    """'LIKE' thumbs-up + 'SUBSCRIBE' button with a ringing bell. Springs in, holds, shrinks out.
    final=True (end of the video) stays until the scene ends."""
    if since < 0:
        return
    out = 0.0 if final else ease_in_out(clamp01((since - hold) / 0.3))
    if out >= 1.0:
        return
    k = ease_out_back(clamp01(since / 0.4)) * (1 - out)
    canvas.save()
    canvas.translate(cx, cy)
    canvas.scale(k, k)
    o = max(3.0, 4.0 * u)
    w, h = 470 * u, 128 * u
    rect = skia.Rect(-w / 2, -h / 2, w / 2, h / 2)
    canvas.drawRRect(skia.RRect.MakeRectXY(rect.makeOffset(6 * u, 8 * u), 28 * u, 28 * u), fill((0, 0, 0), 110))
    canvas.drawRRect(skia.RRect.MakeRectXY(rect, 28 * u, 28 * u), fill((255, 255, 255)))
    canvas.drawRRect(skia.RRect.MakeRectXY(rect, 28 * u, 28 * u), stroke(INK, o))
    # thumbs-up (left)
    tx = -w / 2 + 62 * u
    canvas.save()
    canvas.translate(tx, 4 * u)
    canvas.rotate(-8 + 6 * math.sin(since * 7))
    inked(canvas, poly_path([(-22 * u, -4 * u), (-9 * u, -4 * u), (-9 * u, 26 * u), (-22 * u, 26 * u)]), (66, 133, 244), o * 0.7)
    thumb = skia.Path()
    thumb.moveTo(-9 * u, 26 * u)
    thumb.lineTo(-9 * u, -2 * u)
    thumb.lineTo(2 * u, -22 * u)
    thumb.quadTo(12 * u, -22 * u, 8 * u, -6 * u)
    thumb.lineTo(24 * u, -6 * u)
    thumb.quadTo(30 * u, -4 * u, 27 * u, 6 * u)
    thumb.lineTo(23 * u, 22 * u)
    thumb.quadTo(21 * u, 26 * u, 16 * u, 26 * u)
    thumb.close()
    inked(canvas, thumb, (66, 133, 244), o * 0.7)
    canvas.restore()
    # subscribe button (right) with a ringing bell
    bx0, bx1 = -w / 2 + 120 * u, w / 2 - 22 * u
    btn = skia.Rect(bx0, -34 * u, bx1, 34 * u)
    canvas.drawRRect(skia.RRect.MakeRectXY(btn, 16 * u, 16 * u), fill((230, 33, 23)))
    canvas.drawRRect(skia.RRect.MakeRectXY(btn, 16 * u, 16 * u), stroke(INK, o * 0.8))
    from .thumbnail import _typeface
    font = skia.Font(_typeface(), 30 * u)
    label = "SUBSCRIBE"
    canvas.drawString(label, bx0 + 62 * u, 11 * u, font, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
    canvas.save()
    canvas.translate(bx0 + 30 * u, 0)
    canvas.rotate(18 * math.sin(since * 11) * (1 - out))
    bell = skia.Path()
    bell.moveTo(-13 * u, 14 * u)
    bell.quadTo(-13 * u, -14 * u, 0, -16 * u)
    bell.quadTo(13 * u, -14 * u, 13 * u, 14 * u)
    bell.close()
    inked(canvas, bell, (255, 214, 64), o * 0.6)
    canvas.drawCircle(0, 18 * u, 4 * u, fill((255, 214, 64)))
    canvas.restore()
    canvas.restore()


# ---- sidekick mascot -------------------------------------------------------------------------

def draw_mascot(canvas, x: float, y: float, u: float, t: float, mood: str, look_toward: float,
                mouth: float = 0.0, blink: float = 0.0, c: Color = (150, 120, 230)) -> None:
    """'Pip': a little floating ghost-blob that reacts to the story. Same character every
    video - a consistent personality is what makes a channel feel like a show."""
    bob = math.sin(t * 2.6) * 5 * u
    y = y + bob
    squash = 1.0 + (0.12 if mood == "shocked" else 0.0)
    o = max(2.0, 2.4 * u)
    body = skia.Path()
    body.moveTo(x - 18 * u, y + 4 * u)
    body.cubicTo(x - 20 * u, y - 30 * u * squash, x + 20 * u, y - 30 * u * squash, x + 18 * u, y + 4 * u)
    wav = math.sin(t * 7) * 2.2 * u
    body.quadTo(x + 14 * u, y + 15 * u + wav, x + 8 * u, y + 7 * u)
    body.quadTo(x + 2 * u, y + 17 * u - wav, x - 4 * u, y + 7 * u)
    body.quadTo(x - 11 * u, y + 15 * u + wav, x - 18 * u, y + 4 * u)
    body.close()
    glow(canvas, x, y - 8 * u, 38 * u, c, 70)
    inked(canvas, body, c, o)
    canvas.drawOval(skia.Rect(x - 12 * u, y - 20 * u, x - 4 * u, y - 13 * u), fill(shade(c, 0.45), 190))
    for sd in (-1, 1):
        ex = x + sd * 6.5 * u
        er = 5.2 * u * (1.25 if mood == "shocked" else 1.0)
        ey = y - 9 * u
        if blink > 0.6:
            canvas.drawLine(ex - er, ey, ex + er, ey, stroke(INK, 2.2 * u))
        else:
            canvas.drawCircle(ex, ey, er, fill((255, 255, 255)))
            canvas.drawCircle(ex, ey, er, stroke(INK, o * 0.7))
            canvas.drawCircle(ex + look_toward * 2.0 * u, ey + 0.5 * u, 2.4 * u, fill(INK))
    m = max(mouth, 0.7 if mood == "shocked" else 0.0)
    if m > 0.15:
        canvas.drawOval(skia.Rect(x - 3 * u, y - 3.5 * u, x + 3 * u, y - 3.5 * u + (2 + 5 * m) * u), fill((92, 28, 40)))
    else:
        p = skia.Path()
        p.moveTo(x - 3.5 * u, y - 2.5 * u)
        p.quadTo(x, y + 0.5 * u, x + 3.5 * u, y - 2.5 * u)
        canvas.drawPath(p, stroke(INK, 1.8 * u))
