"""Per-scene renderer: composes a layered parallax set, rigged characters, effects
and a cinematic finish into frames piped straight to ffmpeg (no temp images)."""
from __future__ import annotations

import math
import random
import subprocess
from pathlib import Path
from typing import List, Optional

import numpy as np
import skia

from . import character as C
from . import fx
from .art import Color, col, fill, glow, stroke
from .audio import envelope, sentence_beats
from .direction import SceneDirection
from .easing import clamp01, ease_in_out, ease_out_cubic, lerp, wobble
from .sets import SceneSet, build_set

_SAMPLING = skia.SamplingOptions(skia.FilterMode.kLinear, skia.MipmapMode.kNone)


class _Finish:
    """Vignette + film grain, built once per scene."""

    def __init__(self, w: int, h: int, seed: int, grain: bool = False):
        self.use_grain = grain
        s = skia.Surface(w, h)
        shader = skia.GradientShader.MakeRadial((w / 2, h / 2), math.hypot(w, h) * 0.55,
                                                [col((0, 0, 0), 0), col((0, 0, 0), 0), col((6, 4, 18), 120)], [0.0, 0.55, 1.0])
        s.getCanvas().drawRect(skia.Rect(0, 0, w, h), skia.Paint(Shader=shader))
        self.vignette = s.makeImageSnapshot()
        self.gw = self.gh = 0
        self.rng = random.Random(seed)
        if not grain:
            return  # grain is pure noise: it makes encodes 10x bigger and slower, so it is opt-in
        rng = np.random.default_rng(seed)
        gw, gh = int(w * 1.25), int(h * 1.25)
        g = np.zeros((gh, gw, 4), np.uint8)
        v = (rng.random((gh, gw)) > 0.5) * 255
        g[..., 0] = g[..., 1] = g[..., 2] = v
        g[..., 3] = rng.integers(0, 15, (gh, gw))
        self.grain = skia.Image.fromarray(g, colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType)
        self.gw, self.gh = gw, gh

    def draw(self, canvas, w, h):
        canvas.drawImage(self.vignette, 0, 0)
        if self.use_grain:
            canvas.drawImage(self.grain, -self.rng.uniform(0, self.gw - w), -self.rng.uniform(0, self.gh - h))


def _draw_layer(canvas, layer, cam_x: float, t: float, w: int):
    lw = layer.image.width()
    x = (-(lw - w) / 2 - cam_x * layer.parallax - layer.drift * t) % lw
    if x > 0:
        x -= lw
    while x < w:
        canvas.drawImage(layer.image, x, 0, _SAMPLING)
        x += lw


def _particles(canvas, kind: str, w: int, h: int, t: float, u: float, seed: int):
    rng = random.Random(seed)
    n = {"snow": 70, "embers": 38, "dust": 40, "fireflies": 26, "sparkles": 26, "motes": 30, "birds": 3}.get(kind, 0)
    for i in range(n):
        x0, y0, sp, ph = rng.random(), rng.random(), rng.uniform(0.5, 1.5), rng.uniform(0, 6.28)
        if kind == "snow":
            x = (x0 * w + math.sin(t * 0.9 + ph) * 28 * u) % w
            y = (y0 * h + t * 70 * sp * u) % h
            canvas.drawCircle(x, y, (2.0 + 2.2 * sp) * u, fill((255, 255, 255), 215))
        elif kind == "embers":
            x = (x0 * w + math.sin(t * 1.4 + ph) * 34 * u) % w
            y = (y0 * h - t * 60 * sp * u) % h
            a = int(120 + 120 * abs(math.sin(t * 5 + ph)))
            canvas.drawCircle(x, y, (2.0 + 1.6 * sp) * u, fill((255, 150 + int(60 * sp), 50), a))
        elif kind == "dust":
            x = (x0 * w + t * 22 * sp * u) % w
            y = (y0 * h * 0.8 + 0.1 * h + math.sin(t * 0.7 + ph) * 18 * u)
            canvas.drawCircle(x, y, (1.6 + 1.4 * sp) * u, fill((255, 240, 205), 90))
        elif kind == "fireflies":
            x = (x0 * w + math.sin(t * 0.6 + ph) * 60 * u) % w
            y = (0.35 + 0.55 * y0) * h + math.sin(t * 0.8 + ph * 2) * 30 * u
            a = int(255 * abs(math.sin(t * 1.3 + ph)))
            glow(canvas, x, y, 14 * u, (230, 255, 120), a)
        elif kind == "sparkles":
            x = (x0 * w + math.sin(t * 0.5 + ph) * 20 * u) % w
            y = (y0 * h - t * 16 * sp * u) % h
            r = (2 + 4 * abs(math.sin(t * 3 + ph))) * u
            canvas.drawLine(x - r, y, x + r, y, stroke((255, 244, 190), 2 * u, 200))
            canvas.drawLine(x, y - r, x, y + r, stroke((255, 244, 190), 2 * u, 200))
        elif kind == "motes":
            x = (x0 * w + t * 12 * sp * u + math.sin(t + ph) * 12 * u) % w
            y = (y0 * h + math.sin(t * 0.5 + ph) * 20 * u)
            canvas.drawCircle(x, y, (1.4 + 1.2 * sp) * u, fill((255, 255, 240), 70))
        elif kind == "birds":
            x = ((x0 + t * 0.02 * sp) % 1.0) * w
            y = (0.14 + 0.2 * y0) * h
            flap = math.sin(t * 7 + ph) * 7 * u
            p = skia.Path()
            p.moveTo(x - 14 * u, y + flap)
            p.quadTo(x - 6 * u, y - 6 * u, x, y)
            p.quadTo(x + 6 * u, y - 6 * u, x + 14 * u, y + flap)
            canvas.drawPath(p, stroke((40, 40, 60), 2.4 * u))


def render_scene(direction: SceneDirection, duration: float, w: int, h: int, fps: int,
                 out_path: Path, audio_path: Optional[Path] = None, preset: str = "ultrafast",
                 dump_frames: Optional[List[float]] = None, frames_dir: Optional[Path] = None) -> Path:
    n = max(2, int(round(duration * fps)))
    d = direction
    rng = random.Random(d.seed * 7919 + 13)
    u = h / 1080.0
    scale = 4.75 * u  # figure ~480px tall at 1080p, leaving headroom for emotes
    env = envelope(audio_path, fps, n, seed=d.seed)
    beats = sentence_beats(env, fps)
    scene_set = build_set(d.setting, d.tod, w, h, rng)
    gy = scene_set.ground_y
    finish = _Finish(w, h, d.seed)

    from .. import procedural_illustration as P
    look = C.Look.from_archetype(d.archetype, P._CHARACTER_ARCHETYPES, rng)
    rival_look = C.Look.from_archetype(d.rival, P._CHARACTER_ARCHETYPES, rng)
    extras = []
    if d.action == "crowd":
        for k in range(7):
            extras.append((C.Look.from_archetype(rng.choice(list(P._CHARACTER_ARCHETYPES)), P._CHARACTER_ARCHETYPES, rng),
                           rng.uniform(0.04, 0.96), rng.uniform(0.62, 0.8), rng.uniform(0, 6.28)))
        extras.sort(key=lambda e: e[2])
    side = -1 if d.index % 2 == 0 else 1   # alternate which side the hero stands on
    hero_x = w * (0.5 + side * 0.17)
    facing = -side if d.action != "fight" else 1
    blinks = []
    bt = rng.uniform(0.8, 2.0)
    while bt < duration:
        blinks.append(bt)
        bt += rng.uniform(2.0, 4.6)

    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
           "-an", "-c:v", "libx264", "-preset", preset, "-crf", "21", "-threads", "2", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    surface = skia.Surface(w, h)
    canvas = surface.getCanvas()
    info = skia.ImageInfo.Make(w, h, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    buf = np.zeros((h, w, 4), np.uint8)
    dump = {int(round(x * fps)): x for x in (dump_frames or [])}
    last_beat_t = -9.0
    try:
        for i in range(n):
            t = i / fps
            canvas.clear(skia.ColorBLACK)
            since_beat = min([t - b for b in beats if b <= t] or [9.0])
            beat_k = math.exp(-since_beat * 7.0) if since_beat < 9 else 0.0
            # ---------- camera
            prog = ease_in_out(t / max(duration, 0.1))
            zoom = {"push_in": lerp(1.06, 1.20, prog), "pull_out": lerp(1.20, 1.06, prog)}.get(d.camera, 1.08)
            cam_x = {"pan_right": lerp(-70, 70, prog), "pan_left": lerp(70, -70, prog)}.get(d.camera, lerp(-20, 20, prog)) * u
            if d.role == "hook":
                zoom += 0.22 * math.exp(-t * 5.0)      # opening punch: snaps from tight to settled
            if d.action == "walk":
                cam_x = t * 150 * u
            zoom += 0.012 * beat_k                       # nudge on every sentence start
            shake = 0.0
            if d.mood == "shocked" and t < 1.2:
                shake = 9 * math.exp(-t * 2.4) * u
            if d.action == "fight":
                shake = max(shake, 0.0)
            sx_ = wobble(t * 9, 1.0) * shake
            sy_ = wobble(t * 9, 4.0) * shake
            canvas.save()
            fxp, fyp = hero_x, gy - 230 * u
            canvas.translate(fxp + sx_, fyp + sy_)
            canvas.scale(zoom, zoom)
            canvas.translate(-fxp, -fyp)

            for L in scene_set.layers:
                if not L.front:
                    _draw_layer(canvas, L, cam_x, t, w)

            # ---------- cast
            mouth_v = clamp01((env[i] - 0.12) * 1.6)
            blink = 0.0
            for bt_ in blinks:
                if 0 <= t - bt_ < 0.16:
                    blink = 1 - abs((t - bt_) / 0.08 - 1)
            face = C.Face(mood=d.mood, mouth=0.0, blink=blink, look_x=0.5 * -side)   # story characters act, they don't recite the voiceover
            hx = hero_x
            if d.action == "walk":
                pose = C.pose_walk(t)
                facing = 1
                hx = w * 0.38
            elif d.mood == "shocked" and t < 1.6:
                pose = C.pose_shock(t, t - 0.12)
            elif d.action == "fight":
                pose = C.pose_fight(t, 0.0)
                hx = w * 0.335
            else:
                pose = C.pose_talk(t + beat_k * 0.0, mouth_v, d.seed)
                # new sentence -> restart the gesture phase so arm motion lands on the words
                if since_beat < 9:
                    pose = C.pose_talk(since_beat + 0.0, mouth_v, 0.0)
            if d.action == "crowd":
                for (elook, ex, ey, ph) in extras:
                    exs = ex * w - cam_x * 0.9
                    es = scale * (0.42 + 0.35 * (ey - 0.62) / 0.18)
                    ep = C.pose_idle(t * 1.6 + ph, ph)
                    ep.sh_r = 20 + 60 * max(0.0, math.sin(t * 2 + ph)) if (d.mood == "shocked") else ep.sh_r
                    ep.sh_l = 20 + 60 * max(0.0, math.sin(t * 2.4 + ph * 1.3)) if (d.mood == "shocked") else ep.sh_l
                    C.draw_shadow(canvas, exs, ey * h + 40 * u, es)
                    C.draw_character(canvas, elook, ep, C.Face(mood="neutral", mouth=0.0), exs, ey * h + 40 * u, es, 1 if exs < w / 2 else -1)
            C.draw_shadow(canvas, hx - cam_x * 0.0, gy, scale)
            C.draw_character(canvas, look, pose, face, hx, gy, scale, facing)
            head_x = hx
            head_y = gy - 112 * scale
            if d.action == "fight":
                rival_pose = C.pose_fight(t, 0.55)
                rx_ = w * 0.665
                C.draw_shadow(canvas, rx_, gy, scale)
                C.draw_character(canvas, rival_look, rival_pose, C.Face(mood="serious", mouth=0.0), rx_, gy, scale, -1)
                cyc = (t % 1.1)
                hit = cyc - 0.55
                fx.draw_burst(canvas, (hx + rx_) / 2, gy - 62 * scale, u * 1.2, hit)
                if 0 <= hit < 0.1:
                    canvas.translate(wobble(t * 50) * 5 * u, wobble(t * 50, 2) * 5 * u)
            # ---------- emotes over the hero's head
            for et, kind in d.emotes:
                fx.draw_emote(canvas, kind, head_x + 36 * scale * -facing * 0.3, head_y - 6 * scale, scale, t - et)
            if d.role == "hook" and t < 0.5:
                fx.draw_burst(canvas, hx, gy - 300 * u, u * 2.2, t, 0.5)

            for L in scene_set.layers:
                if L.front:
                    _draw_layer(canvas, L, cam_x, t, w)
            canvas.restore()

            # ---------- screen-space finishing
            if d.tod != "day":
                tintc = (150, 168, 232) if d.tod == "night" else (255, 214, 184)
                canvas.drawRect(skia.Rect(0, 0, w, h), skia.Paint(Color=col(tintc), BlendMode=skia.BlendMode.kMultiply))
            for (lx, ly, lc, lr) in scene_set.lights:
                a = int(110 + 50 * math.sin(t * 11 + lx))
                glow(canvas, lx - cam_x * 0.6 % scene_set.tile_w, ly, lr * (0.92 + 0.08 * math.sin(t * 17 + lx)), lc, a)
            _particles(canvas, scene_set.particles, w, h, t, u, d.seed)
            if d.mood == "shocked":
                fx.draw_speed_lines(canvas, w, h, t - 0.1)
            if d.role == "hook":
                fx.draw_speed_lines(canvas, w, h, t, 0.45, 110)
            if d.mascot and t > 0.2:
                mk = fx.pop_scale(t - 0.2)
                mx = w * (0.86 if side == -1 else 0.14)
                canvas.save()
                canvas.translate(mx, h * 0.2)
                canvas.scale(mk, mk)
                m_mood = "shocked" if (d.mood == "shocked" and t < 3.0) else "neutral"
                fx.draw_mascot(canvas, 0, 0, 2.5 * u, t, m_mood, -side * 0.8, mouth=mouth_v,
                               blink=1.0 if any(0 <= t - b < 0.14 for b in blinks[::-1]) else 0.0)
                canvas.restore()
                if d.role == "insight":
                    fx.draw_emote(canvas, "bulb", mx, h * 0.2 - 40 * u, 2.2 * u, t - 1.6, 2.0)
            finish.draw(canvas, w, h)

            surface.readPixels(info, buf, w * 4, 0, 0)
            if i in dump and frames_dir is not None:
                surface.makeImageSnapshot().save(str(frames_dir / f"{out_path.stem}_{dump[i]:.1f}.png"), skia.kPNG)
            proc.stdin.write(buf)
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg exited with {rc} encoding {out_path}")
    return out_path
