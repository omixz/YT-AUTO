"""Cinematic finishing pass for the illustrated scene clips.

The procedural illustrations are flat, bright cartoon frames - fine as raw
material, but nothing about them feels like a place you're *in*. This pass runs
over each finished scene clip and gives it mood: a story-appropriate colour
grade (cold night / warm dusk / teal-and-orange), a soft bloom, vignette, film
grain, a touch of handheld camera drift on dramatic beats, and a drifting
particle layer (embers, rain, snow, or dust motes) that adds depth and motion.

Everything is an ffmpeg filter chain over the existing clip, so it never
changes a clip's length (audio sync is untouched), and any failure falls back
to the original clip - a styling pass must never be able to break an upload.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .script_writer import Scene

logger = logging.getLogger(__name__)

LOOP_SECONDS = 6


@dataclass(frozen=True)
class Look:
    name: str
    particles: str                    # embers | rain | snow | dust
    contrast: float
    saturation: float
    brightness: float
    gamma: float
    shadows: Tuple[float, float, float]      # colorbalance rs/gs/bs
    highlights: Tuple[float, float, float]   # colorbalance rh/gh/bh
    bloom: float
    particle_opacity: float


_LOOKS: Dict[str, Look] = {
    # Dark, dangerous: war, fire, storms, death.
    "danger": Look("danger", "embers", 1.30, 0.95, -0.22, 0.92, (-0.05, 0.0, 0.10), (0.16, 0.04, -0.12), 0.18, 0.85),
    "storm": Look("storm", "rain", 1.28, 0.80, -0.26, 0.90, (-0.06, 0.02, 0.14), (0.0, 0.04, 0.10), 0.12, 0.70),
    # Cold: snow, ice, winter, the sea at night.
    "cold": Look("cold", "snow", 1.22, 0.85, -0.18, 0.96, (-0.04, 0.02, 0.12), (-0.02, 0.04, 0.12), 0.16, 0.90),
    # Warm: dawn, deserts, ancient empires, resolutions.
    "warm": Look("warm", "dust", 1.18, 1.10, -0.12, 0.97, (0.06, 0.02, -0.06), (0.14, 0.06, -0.10), 0.22, 0.75),
    # Default: the teal-and-orange blockbuster grade.
    "cinema": Look("cinema", "dust", 1.22, 1.05, -0.16, 0.95, (-0.05, 0.0, 0.09), (0.11, 0.03, -0.09), 0.16, 0.70),
}

_KEYWORDS = [
    ("storm", ("storm", "rain", "hurricane", "thunder", "flood", "tempest", "typhoon")),
    ("danger", ("battle", "war", "fire", "burn", "flame", "explosion", "attack", "siege", "soldier", "army",
                "death", "murder", "kill", "disaster", "crash", "fight", "weapon", "bomb", "dark", "night",
                "fear", "terror", "plague", "danger", "blood", "invasion")),
    ("cold", ("snow", "ice", "winter", "arctic", "frozen", "blizzard", "antarctic", "polar", "ocean", "sea",
              "ship", "submarine", "sink")),
    ("warm", ("dawn", "sunrise", "sunset", "desert", "gold", "golden", "empire", "ancient", "ruin", "temple",
              "king", "queen", "pyramid", "victory", "hope", "dusk")),
]


def look_for_scene(scene: Scene) -> Look:
    text = f"{scene.narration} {' '.join(scene.visual_keywords)}".lower()
    for name, words in _KEYWORDS:
        if any(w in text for w in words):
            return _LOOKS[name]
    return _LOOKS["cinema"]


# --- particle layer ---------------------------------------------------------

def _render_particles(kind: str, w: int, h: int, fps: int, out: Path) -> Path:
    """A seamlessly looping LOOP_SECONDS clip of drifting specks on black,
    screen-blended over the scene. Positions are modular in time (velocity is a
    whole number of screen-heights per loop), so the loop has no visible seam."""
    rng = np.random.default_rng({"embers": 1, "rain": 2, "snow": 3, "dust": 4}[kind])
    frames = LOOP_SECONDS * fps
    if kind == "rain":
        n = 170
    elif kind == "snow":
        n = 120
    elif kind == "embers":
        n = 70
    else:
        n = 55
    grain = np.random.default_rng(99)
    x0 = rng.uniform(0, w, n)
    y0 = rng.uniform(0, h, n)
    size = rng.uniform(1.4, 4.5, n) if kind != "dust" else rng.uniform(2.0, 7.0, n)
    k = rng.integers(1, 4, n)                    # whole screen-heights travelled per loop
    sway = rng.uniform(10, 60, n)
    m = rng.integers(1, 3, n)
    phase = rng.uniform(0, 2 * np.pi, n)
    twinkle = rng.integers(2, 6, n)

    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
           "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for f in range(frames):
            u = f / frames
            img = Image.new("RGB", (w, h), (0, 0, 0))
            d = ImageDraw.Draw(img)
            for i in range(n):
                if kind == "embers":
                    y = (y0[i] - k[i] * h * u) % h            # rise
                    x = x0[i] + sway[i] * np.sin(2 * np.pi * m[i] * u + phase[i])
                    flick = 0.55 + 0.45 * np.sin(2 * np.pi * twinkle[i] * u + phase[i])
                    c = (int(255 * flick), int(120 * flick), int(30 * flick))
                    d.ellipse([x - size[i], y - size[i], x + size[i], y + size[i]], fill=c)
                elif kind == "rain":
                    y = (y0[i] + k[i] * h * u * 2) % h        # fall fast
                    x = (x0[i] - 0.18 * (y - y0[i])) % w
                    d.line([(x, y), (x - 9, y + 38)], fill=(150, 165, 190), width=2)
                elif kind == "snow":
                    y = (y0[i] + k[i] * h * u) % h
                    x = x0[i] + sway[i] * np.sin(2 * np.pi * m[i] * u + phase[i])
                    d.ellipse([x - size[i], y - size[i], x + size[i], y + size[i]], fill=(235, 240, 255))
                else:                                           # dust motes: slow, soft, floaty
                    y = (y0[i] - k[i] * h * u * 0.5) % h if k[i] > 1 else (y0[i] + h * u * 0.0) % h
                    x = x0[i] + sway[i] * np.sin(2 * np.pi * m[i] * u + phase[i])
                    flick = 0.45 + 0.55 * np.sin(2 * np.pi * twinkle[i] * u + phase[i]) ** 2
                    c = (int(255 * flick), int(235 * flick), int(200 * flick))
                    d.ellipse([x - size[i], y - size[i], x + size[i], y + size[i]], fill=c)
            blur = 2.2 if kind == "dust" else 0.9
            img = img.filter(ImageFilter.GaussianBlur(blur))
            arr = np.asarray(img, dtype=np.int16) + grain.integers(0, 14, (h, w, 1), dtype=np.int16)  # film grain
            proc.stdin.write(np.clip(arr, 0, 255).astype(np.uint8).tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"particle render failed ({kind})")
    return out


_PARTICLE_CACHE: Dict[Tuple[str, int, int, int], Path] = {}


def _particles(kind: str, w: int, h: int, fps: int, work_dir: Path) -> Path:
    key = (kind, w, h, fps)
    cached = _PARTICLE_CACHE.get(key)
    if cached and cached.exists():
        return cached
    # Specks are soft anyway: render at half size (4x cheaper), the filter graph scales up.
    path = _render_particles(kind, w // 2, h // 2, fps, work_dir / f"fx_{kind}_{w}x{h}.mp4")
    _PARTICLE_CACHE[key] = path
    return path


# --- grading ----------------------------------------------------------------

def _curves(look: Look) -> str:
    """Per-look grade as one `curves` filter. It is a LUT (fast); eq+colorbalance
    cost ~4x the encode itself, which would add ~an hour to a 20-minute render."""
    c = look.contrast
    lo, hi = max(0.05, 0.25 - 0.35 * (c - 1)), min(0.95, 0.75 + 0.35 * (c - 1))
    mid = 0.5 + look.brightness * 0.5

    def ch(sh: float, hl: float) -> str:
        pts = [(0.0, max(0.0, sh * 0.4)), (0.25, 0.25 + sh * 0.8), (0.75, min(0.98, 0.75 + hl * 0.8)), (1.0, min(1.0, 1.0 + hl * 0.1))]
        return " ".join(f"{x:.3f}/{max(0.0, min(1.0, y)):.3f}" for x, y in pts)

    # Pull the near-white skies down (highlights -> ~0.9), not just the midtones.
    white = min(1.0, 0.97 + look.brightness * 0.35)
    hi_out = min(0.95, 0.75 + look.brightness * 0.5)
    master = f"0/0 {lo:.3f}/{0.25 * 0.72:.3f} 0.5/{mid:.3f} {hi:.3f}/{hi_out:.3f} 1/{white:.3f}"
    return (f"curves=master='{master}':r='{ch(look.shadows[0], look.highlights[0])}':"
            f"g='{ch(look.shadows[1], look.highlights[1])}':b='{ch(look.shadows[2], look.highlights[2])}'")


# NOTE: every blend runs in RGB (gbrp). In YUV, `blend=screen` also screens the
# U/V chroma planes against their neutral 128, which tints the whole frame magenta.
def _filter_graph(look: Look, scene: Scene, w: int, h: int) -> str:
    shake = scene.role == "hook" or look.name in ("danger", "storm")
    amp_x, amp_y = (8, 6) if scene.role == "hook" else (4, 3)
    pre = ""
    if shake:
        pre = (f"scale={int(w * 1.06)}:{int(h * 1.06)},"
               f"crop={w}:{h}:x='(iw-{w})/2+sin(t*9.0)*{amp_x}':y='(ih-{h})/2+cos(t*7.3)*{amp_y}',")
    glow = 0.45 if scene.role == "insight" else 1.0
    return (
        f"[0:v]{pre}scale={w}:{h},setsar=1,format=gbrp,{_curves(look)},"
        f"split[a][b];[b]scale={w // 4}:{h // 4},gblur=sigma=5,scale={w}:{h}[bl];"
        f"[a][bl]blend=all_mode=screen:all_opacity={round(look.bloom * glow, 3)},"
        f"vignette=angle=PI/2.7,format=gbrp[g];"
        f"[1:v]scale={w}:{h},format=gbrp[p];"
        f"[g][p]blend=all_mode=screen:all_opacity={look.particle_opacity}:shortest=1,format=yuv420p[v]"
    )


def grade_clip(clip: Path, scene: Scene, w: int, h: int, fps: int, work_dir: Path) -> Path:
    """Returns the graded clip path, or the original clip if anything fails."""
    look = look_for_scene(scene)
    out = clip.with_name(clip.stem + "_cine.mp4")
    try:
        fx = _particles(look.particles, w, h, fps, work_dir)
        cmd = ["ffmpeg", "-loglevel", "error", "-y", "-i", str(clip), "-stream_loop", "-1", "-i", str(fx),
               "-filter_complex", _filter_graph(look, scene, w, h), "-map", "[v]", "-map", "0:a?",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(fps), "-c:a", "copy",
               "-shortest", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not out.exists() or out.stat().st_size < 1000:
            logger.warning("Cinematic pass failed for %s (%s); using the original clip.", clip.name, r.stderr[-300:])
            return clip
        return out
    except Exception as exc:  # noqa: BLE001 - styling must never break a render
        logger.warning("Cinematic pass skipped for %s: %s", clip.name, exc)
        return clip


def grade_all(clips: List[Path], scenes: List[Scene], w: int, h: int, fps: int, work_dir: Path,
              budget_seconds: float = 1500) -> List[Path]:
    """Grades every clip in order. Past `budget_seconds` the remaining clips are
    left ungraded, so styling can never turn a ~40-minute render into a runaway."""
    import time
    start = time.monotonic()
    graded = []
    for n, (clip, scene) in enumerate(zip(clips, scenes)):
        if time.monotonic() - start > budget_seconds:
            logger.warning("Cinematic budget (%ss) reached after %d/%d clips; leaving the rest ungraded.",
                           budget_seconds, n, len(clips))
            graded.extend(Path(c) for c in clips[n:])
            break
        graded.append(grade_clip(Path(clip), scene, w, h, fps, work_dir))
    return graded
