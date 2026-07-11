"""Procedural stick-figure + icon + kinetic-typography overlay, composited
onto real stock footage/photos for longform videos. The figure/icon/caption
layer is rendered on a pure-black canvas and combined with a real Pexels
background via ffmpeg's colorkey filter (black -> transparent) - avoids the
complexity of true alpha-channel video encoding while still compositing
cleanly, since the overlay only ever draws in the accent/white colors.
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw

from . import assembler
from .config import PipelineConfig
from .fonts import load_bold
from .script_writer import Scene
from .visuals import VisualAsset

OVERLAY_BG = (0, 0, 0)
# Props are drawn in a darker neutral tone rather than the accent color -
# against a solid white head, a same-color outline is invisible. Dark enough
# to read clearly, far enough from pure black to survive the overlay's
# colorkey compositing (which keys out near-black as transparent).
PROP_COLOR = (60, 60, 60)


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


def _draw_stick_figure(
    draw: ImageDraw.ImageDraw, cx: float, cy: float, scale: float, pose: dict,
    color: tuple, bob: float, prop: Optional[str] = None,
) -> None:
    hip = (cx, cy + bob)
    head_r = 0.18 * scale
    torso_len = 0.55 * scale
    limb_len = 0.32 * scale
    width = max(3, round(scale * 0.02))

    shoulder = (hip[0], hip[1] - torso_len)
    head_c = (shoulder[0], shoulder[1] - head_r * 1.3)

    arm_l_end = _limb_end(shoulder, pose["arm_l"], limb_len)
    arm_r_end = _limb_end(shoulder, pose["arm_r"], limb_len)
    leg_l_end = _limb_end(hip, pose["leg_l"], limb_len * 1.3)
    leg_r_end = _limb_end(hip, pose["leg_r"], limb_len * 1.3)

    def dot(point: Tuple[float, float], r: float) -> None:
        draw.ellipse([point[0] - r, point[1] - r, point[0] + r, point[1] + r], fill=color)

    cap_r = width / 2
    for a, b in ((shoulder, hip), (shoulder, arm_l_end), (shoulder, arm_r_end),
                 (hip, leg_l_end), (hip, leg_r_end)):
        draw.line([a, b], fill=color, width=width)
        dot(a, cap_r)
        dot(b, cap_r)

    # Solid head (rather than an outline) for a bolder, modern pictogram look.
    draw.ellipse(
        [head_c[0] - head_r, head_c[1] - head_r, head_c[0] + head_r, head_c[1] + head_r],
        fill=color,
    )

    if prop and prop in _PROP_DRAWERS:
        _PROP_DRAWERS[prop](draw, head_c, head_r, PROP_COLOR, width)


# --- topic-relevant props (drawn on/above the head) - a lightweight "costume"
# system so the figure isn't always the same generic silhouette: a war/
# military topic gets a helmet, a royalty/medieval topic gets a crown, etc. --

def _prop_helmet(draw: ImageDraw.ImageDraw, head_c: Tuple[float, float], head_r: float, color: tuple, width: int) -> None:
    cx, cy = head_c
    r = head_r * 1.2
    draw.pieslice([cx - r, cy - r * 1.05, cx + r, cy + r * 0.35], 180, 360, outline=color, width=width)
    draw.line([(cx - r, cy), (cx + r, cy)], fill=color, width=width)


def _prop_crown(draw: ImageDraw.ImageDraw, head_c: Tuple[float, float], head_r: float, color: tuple, width: int) -> None:
    cx, cy = head_c
    base_y = cy - head_r * 1.05
    mid_y = cy - head_r * 1.5
    top_y = cy - head_r * 2.0
    points = [
        (cx - head_r * 1.1, base_y),
        (cx - head_r * 1.1, mid_y),
        (cx - head_r * 0.55, top_y),
        (cx, mid_y),
        (cx + head_r * 0.55, top_y),
        (cx + head_r * 1.1, mid_y),
        (cx + head_r * 1.1, base_y),
    ]
    draw.line(points, fill=color, width=width)
    draw.line([points[0], points[-1]], fill=color, width=width)


def _prop_hat(draw: ImageDraw.ImageDraw, head_c: Tuple[float, float], head_r: float, color: tuple, width: int) -> None:
    cx, cy = head_c
    brim_y = cy - head_r * 0.75
    draw.ellipse(
        [cx - head_r * 1.6, brim_y - head_r * 0.18, cx + head_r * 1.6, brim_y + head_r * 0.18],
        outline=color, width=width,
    )
    draw.rectangle([cx - head_r * 0.7, cy - head_r * 1.9, cx + head_r * 0.7, brim_y], outline=color, width=width)


_PROP_DRAWERS = {
    "helmet": _prop_helmet,
    "crown": _prop_crown,
    "hat": _prop_hat,
}

_KEYWORD_TO_PROP = [
    (("soldier", "army", "military", "war", "battle", "troops", "combat", "invasion", "regiment"), "helmet"),
    (("king", "queen", "royal", "monarch", "throne", "kingdom", "empire", "emperor", "medieval", "castle"), "crown"),
    (("detective", "spy", "noir", "crime", "gangster", "mafia"), "hat"),
]


def _prop_for_scene(scene: Scene) -> Optional[str]:
    haystack = " ".join(scene.visual_keywords).lower()
    for keywords, prop_name in _KEYWORD_TO_PROP:
        if any(kw in haystack for kw in keywords):
            return prop_name
    return None


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


def _capped_line(draw: ImageDraw.ImageDraw, a: Tuple[float, float], b: Tuple[float, float], color: tuple, width: int) -> None:
    draw.line([a, b], fill=color, width=width)
    r = width / 2
    for p in (a, b):
        draw.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=color)


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
    _capped_line(draw, handle_start, handle_end, color, width * 2)


def _draw_clock(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color: tuple, width: int) -> None:
    r = size * 0.35
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=width)
    _capped_line(draw, (cx, cy), (cx, cy - r * 0.6), color, width)
    _capped_line(draw, (cx, cy), (cx + r * 0.4, cy + r * 0.2), color, width)


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
    """Mutates frame in place, compositing faded-in kinetic-typography text
    in the gap between the icon and the figure's head. Deliberately NOT
    bottom-anchored: assembler.py separately burns in the real narration-
    synced SRT captions along the bottom for every format, so this on-screen
    text (a short optional headline) would collide with those down there."""
    if not text:
        return
    size = frame.size
    scratch_draw = ImageDraw.Draw(frame)
    font = load_bold(round(size[0] * 0.03))
    max_width = round(size[0] * 0.7)

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
    lines = lines[:2]

    # Ease-in slide-up + fade-in over the first 25% of the scene.
    fade_t = min(1.0, t / 0.25)
    y_offset = round((1 - fade_t) * size[1] * 0.03)
    alpha = round(255 * fade_t)

    line_h = round(font.size * 1.3)
    y = round(size[1] * 0.34) + y_offset

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

def render_overlay(scene: Scene, duration: float, config: PipelineConfig, out_path: Path) -> Path:
    """Renders the stick-figure/icon/caption layer as an animated mp4 (silent,
    exact duration, already at config.video.resolution) on a pure-black
    background, meant to be composited onto real footage via compose_scene."""
    size = config.video.resolution
    fps = config.animation.fps
    accent = tuple(config.animation.accent_color)

    frame_count = max(1, round(duration * fps))

    background = Image.new("RGB", size, OVERLAY_BG)
    icon_name = _icon_for_scene(scene)
    icon_drawer = _ICON_DRAWERS[icon_name]
    prop = _prop_for_scene(scene)

    # Sized off height (the constrained dimension once icon/figure/caption
    # are stacked vertically), not width - keeps proportions sane in landscape.
    # figure_cy is pushed low enough that the head (which sits well above the
    # hip - see _draw_stick_figure) clears the caption band drawn at ~34-48%
    # of frame height, so on-screen text never overlaps the figure's head.
    figure_cx, figure_cy = size[0] * 0.5, size[1] * 0.74
    figure_scale = size[1] * 0.28
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
            _draw_stick_figure(draw, figure_cx, figure_cy, figure_scale, pose, accent, bob, prop)

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


def compose_scene(
    scene: Scene, duration: float, background_asset: VisualAsset,
    config: PipelineConfig, work_dir: Path, out_path: Path,
) -> Path:
    """Renders the animated overlay and composites it onto a real stock-
    footage/photo background (reusing assembler's scale/crop/loop and Ken
    Burns handling), via ffmpeg colorkey - the overlay's pure-black
    background becomes transparent, its white figure/icon/text stays."""
    overlay_path = work_dir / f"{out_path.stem}_overlay.mp4"
    render_overlay(scene, duration, config, overlay_path)

    bg_path = work_dir / f"{out_path.stem}_bg.mp4"
    assembler.build_video_segment(background_asset, duration, config, bg_path)

    assembler.run_ffmpeg([
        "ffmpeg", "-y", "-i", str(bg_path), "-i", str(overlay_path),
        "-filter_complex",
        # Darken the real footage a bit first so white line art stays legible
        # over bright/busy source material, then key out the overlay's black.
        "[0:v]eq=brightness=-0.12:contrast=0.92[bgdark];"
        "[1:v]colorkey=0x000000:0.15:0.05[fg];"
        "[bgdark][fg]overlay=format=auto[out]",
        "-map", "[out]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_path),
    ])
    return out_path
