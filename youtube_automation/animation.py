"""Procedural stick-figure + icon + kinetic-typography renderer for longform
videos - a zero-API-cost stand-in for AI-illustrated animation. Draws each
scene as a PNG frame sequence with Pillow, then encodes it with ffmpeg,
matched to that scene's exact narration duration. Used for `longform` only;
`shorts` keep the Pexels stock-footage pipeline in visuals.py.
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw

from .config import PipelineConfig
from .fonts import load_bold
from .script_writer import Scene

BG_TOP = (20, 22, 38)
BG_BOTTOM = (34, 38, 66)


# --- background ---------------------------------------------------------

def _gradient_background(size: Tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        color = tuple(round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=color)
    return img


# --- stick figure ---------------------------------------------------------

def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


_POSES = {
    "idle":     {"arm_l": -25, "arm_r": 25, "leg_l": -10, "leg_r": 10},
    "arms_up":  {"arm_l": -135, "arm_r": 135, "leg_l": -10, "leg_r": 10},
    "point":    {"arm_l": -25, "arm_r": 100, "leg_l": -10, "leg_r": 10},
    "thinking": {"arm_l": -25, "arm_r": -140, "leg_l": -10, "leg_r": 10},
}

ROLE_POSE_SEQUENCE = {
    "hook": ["idle", "arms_up"],
    "build": ["idle", "point"],
    "insight": ["idle", "thinking"],
}


def _pose_for(role: str, t: float) -> dict:
    sequence = ROLE_POSE_SEQUENCE.get(role, ["idle", "point"])
    a, b = _POSES[sequence[0]], _POSES[sequence[-1]]
    blend = (math.sin(t * math.pi * 2) + 1) / 2
    return {k: _lerp(a[k], b[k], blend) for k in a}


def _limb_end(origin: Tuple[float, float], angle_deg: float, length: float) -> Tuple[float, float]:
    rad = math.radians(angle_deg)
    return (origin[0] + length * math.sin(rad), origin[1] + length * math.cos(rad))


def _draw_stick_figure(draw: ImageDraw.ImageDraw, cx: float, cy: float, scale: float, pose: dict, color: tuple, bob: float) -> None:
    hip = (cx, cy + bob)
    head_r = 0.18 * scale
    torso_len = 0.55 * scale
    limb_len = 0.32 * scale
    width = max(3, round(scale * 0.02))

    shoulder = (hip[0], hip[1] - torso_len)
    head_c = (shoulder[0], shoulder[1] - head_r * 1.3)

    arm_l_end = _limb_end(shoulder, pose["arm_l"], limb_len)
    arm_r_end = _limb_end(shoulder, pose["arm_r"], limb_len)
    leg_l_end = _limb_end(hip, 180 + pose["leg_l"], limb_len * 1.3)
    leg_r_end = _limb_end(hip, 180 + pose["leg_r"], limb_len * 1.3)

    draw.line([shoulder, hip], fill=color, width=width)
    draw.line([shoulder, arm_l_end], fill=color, width=width)
    draw.line([shoulder, arm_r_end], fill=color, width=width)
    draw.line([hip, leg_l_end], fill=color, width=width)
    draw.line([hip, leg_r_end], fill=color, width=width)
    draw.ellipse(
        [head_c[0] - head_r, head_c[1] - head_r, head_c[0] + head_r, head_c[1] + head_r],
        outline=color, width=width,
    )


# --- icon library (drawn with primitives, not glyphs - keeps it fully
# code-generated with no font/emoji-coverage dependency) -------------------

def _draw_lightbulb(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: tuple, width: int) -> None:
    r = size * 0.35
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=width)
    draw.line([(cx - r * 0.4, cy + r), (cx - r * 0.4, cy + r * 1.6)], fill=color, width=width)
    draw.line([(cx + r * 0.4, cy + r), (cx + r * 0.4, cy + r * 1.6)], fill=color, width=width)
    draw.line([(cx - r * 0.5, cy + r * 1.6), (cx + r * 0.5, cy + r * 1.6)], fill=color, width=width)


def _draw_question_mark(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: tuple, width: int) -> None:
    font = load_bold(round(size * 1.3))
    bbox = draw.textbbox((0, 0), "?", font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - w / 2 - bbox[0], cy - h / 2 - bbox[1]), "?", font=font, fill=color)


def _draw_exclamation(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: tuple, width: int) -> None:
    font = load_bold(round(size * 1.3))
    bbox = draw.textbbox((0, 0), "!", font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - w / 2 - bbox[0], cy - h / 2 - bbox[1]), "!", font=font, fill=color)


def _draw_chart_bars(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: tuple, width: int) -> None:
    bar_w = size * 0.18
    heights = [0.4, 0.7, 1.0]
    gap = size * 0.08
    total_w = bar_w * 3 + gap * 2
    x = cx - total_w / 2
    for h_frac in heights:
        bar_h = size * 0.6 * h_frac
        draw.rectangle([x, cy + size * 0.3 - bar_h, x + bar_w, cy + size * 0.3], outline=color, width=width)
        x += bar_w + gap


def _draw_magnifying_glass(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: tuple, width: int) -> None:
    r = size * 0.28
    lens_cx, lens_cy = cx - size * 0.08, cy - size * 0.08
    draw.ellipse([lens_cx - r, lens_cy - r, lens_cx + r, lens_cy + r], outline=color, width=width)
    handle_start = (lens_cx + r * 0.7, lens_cy + r * 0.7)
    handle_end = (cx + size * 0.35, cy + size * 0.35)
    draw.line([handle_start, handle_end], fill=color, width=width * 2)


def _draw_clock(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: tuple, width: int) -> None:
    r = size * 0.35
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=width)
    draw.line([(cx, cy), (cx, cy - r * 0.6)], fill=color, width=width)
    draw.line([(cx, cy), (cx + r * 0.4, cy + r * 0.2)], fill=color, width=width)


def _draw_map_pin(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: tuple, width: int) -> None:
    r = size * 0.28
    draw.ellipse([cx - r, cy - r * 1.3, cx + r, cy + r * 0.7], outline=color, width=width)
    draw.polygon([(cx - r * 0.5, cy + r * 0.3), (cx + r * 0.5, cy + r * 0.3), (cx, cy + r * 1.6)], outline=color, width=width)
    inner_r = r * 0.35
    draw.ellipse([cx - inner_r, cy - r * 0.3 - inner_r, cx + inner_r, cy - r * 0.3 + inner_r], outline=color, width=width)


def _draw_star(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: tuple, width: int) -> None:
    points = []
    for i in range(10):
        angle = math.pi / 2 + i * math.pi / 5
        r = size * 0.35 if i % 2 == 0 else size * 0.15
        points.append((cx + r * math.cos(angle), cy - r * math.sin(angle)))
    draw.polygon(points, outline=color, width=width)


_ICON_DRAWERS = {
    "lightbulb": _draw_lightbulb,
    "question": _draw_question_mark,
    "exclamation": _draw_exclamation,
    "chart": _draw_chart_bars,
    "search": _draw_magnifying_glass,
    "clock": _draw_clock,
    "pin": _draw_map_pin,
    "star": _draw_star,
}

_KEYWORD_TO_ICON = [
    (("idea", "insight", "why", "reason", "lightbulb"), "lightbulb"),
    (("mystery", "unknown", "unsolved", "question", "vanish", "disappear"), "question"),
    (("danger", "warning", "twist", "shock", "sudden"), "exclamation"),
    (("data", "statistic", "number", "chart", "percent", "study"), "chart"),
    (("search", "investigat", "detective", "clue", "evidence"), "search"),
    (("clock", "time", "century", "year", "decade", "history", "ancient"), "clock"),
    (("map", "place", "town", "city", "location", "country", "island"), "pin"),
]


def _icon_for_scene(scene: Scene) -> str:
    haystack = " ".join(scene.visual_keywords).lower()
    for keywords, icon_name in _KEYWORD_TO_ICON:
        if any(kw in haystack for kw in keywords):
            return icon_name
    return "star"


# --- kinetic typography ---------------------------------------------------

def _draw_caption(frame: Image.Image, text: str, t: float, color: tuple) -> None:
    """Mutates frame in place, compositing faded-in kinetic-typography text."""
    if not text:
        return
    size = frame.size
    scratch_draw = ImageDraw.Draw(frame)
    font = load_bold(round(size[0] * 0.045))
    max_width = round(size[0] * 0.8)

    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if scratch_draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    lines = lines[:3]

    # Ease-in slide-up + fade-in over the first 25% of the scene.
    fade_t = min(1.0, t / 0.25)
    y_offset = round((1 - fade_t) * size[1] * 0.04)
    alpha = round(255 * fade_t)

    line_h = round(font.size * 1.3)
    total_h = line_h * len(lines)
    y = size[1] - round(size[1] * 0.14) - total_h + y_offset

    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    for line in lines:
        w = odraw.textlength(line, font=font)
        odraw.text(
            ((size[0] - w) / 2, y), line, font=font, fill=(*color, alpha),
            stroke_width=max(2, round(font.size * 0.06)), stroke_fill=(0, 0, 0, alpha),
        )
        y += line_h

    composited = Image.alpha_composite(frame.convert("RGBA"), overlay).convert("RGB")
    frame.paste(composited, (0, 0))


# --- frame rendering + encoding --------------------------------------------

def render_scene(scene: Scene, duration: float, config: PipelineConfig, out_path: Path) -> Path:
    """Renders one scene as an animated mp4 (silent, exact duration, already
    at config.video.resolution) using only Pillow + ffmpeg."""
    size = config.video.resolution
    fps = config.animation.fps
    accent = tuple(config.animation.accent_color)

    frame_count = max(1, round(duration * fps))

    background = _gradient_background(size)
    icon_name = _icon_for_scene(scene)
    icon_drawer = _ICON_DRAWERS[icon_name]

    # Sized off height (the constrained dimension once icon/figure/caption
    # are stacked vertically), not width - keeps proportions sane in landscape.
    figure_cx, figure_cy = size[0] * 0.5, size[1] * 0.62
    figure_scale = size[1] * 0.30
    icon_cx, icon_cy = size[0] * 0.5, size[1] * 0.22
    icon_size = size[1] * 0.16

    # Pipe raw frames straight into ffmpeg's stdin rather than writing (and
    # then re-reading) thousands of compressed PNGs - an order of magnitude
    # faster, which matters once a longform video needs 10,000+ frames.
    proc = subprocess.Popen(
        [
            "ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{size[0]}x{size[1]}", "-framerate", str(fps), "-i", "-",
            "-t", f"{duration:.3f}", "-vf", "format=yuv420p",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_path),
        ],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )

    try:
        for i in range(frame_count):
            t = i / frame_count
            frame = background.copy()
            draw = ImageDraw.Draw(frame)

            bob = math.sin(t * math.pi * 4) * size[1] * 0.01
            pose = _pose_for(scene.role, t)
            _draw_stick_figure(draw, figure_cx, figure_cy, figure_scale, pose, accent, bob)

            icon_bob = math.sin(t * math.pi * 3 + 1) * size[1] * 0.015
            icon_width = max(2, round(icon_size * 0.05))
            icon_drawer(draw, icon_cx, icon_cy + icon_bob, icon_size, accent, icon_width)

            _draw_caption(frame, scene.on_screen_text, t, (255, 255, 255))

            proc.stdin.write(frame.tobytes())

        proc.stdin.close()
        proc.wait()
    finally:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()

    if proc.returncode != 0:
        stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
        raise RuntimeError(f"ffmpeg failed rendering {out_path}:\n{stderr[-4000:]}")

    return out_path
