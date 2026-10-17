"""Render a short demo reel of the cartoon engine - no API keys, no network.

    python -m youtube_automation.toon.sample [--out DIR] [--width 1280]

Used by the manual 'Toon preview' workflow so you can watch the new look before
trusting it with a real upload."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from ..script_writer import Scene
from . import direction
from .engine import render_scene

DEMO = [
    ("In 1492 the sailors vanished into a mystery that nobody could explain.", ["ship", "ocean", "mystery"], "hook"),
    ("The pharaoh gathered his council in the great temple of ancient Egypt.", ["pharaoh", "temple", "court"], "build"),
    ("At midnight the viking raiders fought a bloody duel in the ruined fortress.", ["viking", "fight", "ruins"], "build"),
    ("The knight marched through the snow, afraid of the danger ahead.", ["knight", "snow", "march"], "build"),
    ("Then the prisoner discovered the hidden treasure beneath the dungeon.", ["prison", "dungeon", "treasure"], "build"),
    ("And that is why the whole world still remembers this story.", ["city", "crowd", "celebrate"], "insight"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="toon_sample")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--fps", type=int, default=24)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    w, h = a.width, a.width * 9 // 16
    scenes = [Scene(n, k, r) for n, k, r in DEMO]
    dirs = direction.direct(scenes, [a.seconds] * len(scenes))
    clips = []
    for d in dirs:
        p = out / f"demo_{d.index}.mp4"
        print(f"scene {d.index}: {d.setting}/{d.tod} {d.archetype} {d.action} {d.mood}")
        render_scene(d, a.seconds, w, h, a.fps, p, None, dump_frames=[1.5], frames_dir=out)
        clips.append(p)
    lst = out / "list.txt"
    lst.write_text("".join(f"file '{c.name}'\n" for c in clips))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                    str(out / "toon_demo_reel.mp4")], check=True)
    print("wrote", out / "toon_demo_reel.mp4")


if __name__ == "__main__":
    main()
