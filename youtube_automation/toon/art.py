"""Skia drawing helpers: the cartoon 'ink' style (flat fills, bold dark outline)."""
from __future__ import annotations

from typing import Iterable, Sequence, Tuple

import skia

Color = Tuple[int, int, int]
INK: Color = (27, 27, 47)


def col(c: Color, a: int = 255) -> int:
    return skia.ColorSetARGB(a, int(c[0]), int(c[1]), int(c[2]))


def shade(c: Color, amt: float) -> Color:
    """amt>0 lightens toward white, amt<0 darkens toward black."""
    if amt >= 0:
        return tuple(int(v + (255 - v) * amt) for v in c)  # type: ignore[return-value]
    return tuple(int(v * (1 + amt)) for v in c)  # type: ignore[return-value]


def fill(c: Color, a: int = 255) -> "skia.Paint":
    return skia.Paint(AntiAlias=True, Color=col(c, a), Style=skia.Paint.kFill_Style)


def stroke(c: Color, w: float, a: int = 255) -> "skia.Paint":
    return skia.Paint(AntiAlias=True, Color=col(c, a), Style=skia.Paint.kStroke_Style,
                      StrokeWidth=w, StrokeCap=skia.Paint.kRound_Cap, StrokeJoin=skia.Paint.kRound_Join)


def poly_path(pts: Sequence[Tuple[float, float]], close: bool = True) -> "skia.Path":
    p = skia.Path()
    p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    if close:
        p.close()
    return p


def inked(canvas: "skia.Canvas", path: "skia.Path", c: Color, w: float) -> None:
    """Flat fill plus a bold outline - the signature cartoon look."""
    canvas.drawPath(path, fill(c))
    canvas.drawPath(path, stroke(INK, w))


def inked_circle(canvas, cx, cy, r, c: Color, w: float) -> None:
    canvas.drawCircle(cx, cy, r, fill(c))
    canvas.drawCircle(cx, cy, r, stroke(INK, w))


def inked_oval(canvas, cx, cy, rx, ry, c: Color, w: float) -> None:
    rect = skia.Rect(cx - rx, cy - ry, cx + rx, cy + ry)
    canvas.drawOval(rect, fill(c))
    canvas.drawOval(rect, stroke(INK, w))


def limb(canvas, pts: Iterable[Tuple[float, float]], width: float, c: Color, outline: float) -> None:
    """A thick rounded polyline (arm/leg): outline pass underneath, colour pass on top."""
    path = poly_path(list(pts), close=False)
    canvas.drawPath(path, stroke(INK, width + outline * 2))
    canvas.drawPath(path, stroke(c, width))


def vgradient(top: Color, bottom: Color, y0: float, y1: float):
    return skia.GradientShader.MakeLinear([(0, y0), (0, y1)], [col(top), col(bottom)])


def glow(canvas, cx, cy, r, c: Color, a: int = 120) -> None:
    shader = skia.GradientShader.MakeRadial((cx, cy), r, [col(c, a), col(c, 0)])
    canvas.drawCircle(cx, cy, r, skia.Paint(AntiAlias=True, Shader=shader))
