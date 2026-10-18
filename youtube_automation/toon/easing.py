"""Tiny easing/noise helpers shared by the toon engine."""
from __future__ import annotations

import math


def clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def ease_in_out(t: float) -> float:
    t = clamp01(t)
    return t * t * (3 - 2 * t)


def ease_out_cubic(t: float) -> float:
    return 1 - (1 - clamp01(t)) ** 3


def ease_out_back(t: float, s: float = 1.70158) -> float:
    t = clamp01(t) - 1
    return t * t * ((s + 1) * t + s) + 1


def wobble(t: float, seed: float = 0.0) -> float:
    """Smooth pseudo-random value in about [-1, 1] - cheap handheld shake / idle sway."""
    return (math.sin(t * 1.7 + seed) + 0.6 * math.sin(t * 2.9 + seed * 2.3)
            + 0.3 * math.sin(t * 5.3 + seed * 0.7)) / 1.9
