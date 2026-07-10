"""Builds one SRT caption file for the whole video from per-scene word cues."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import List

from .tts import SceneAudio

WORDS_PER_CAPTION = 4


def _srt_timestamp(seconds: float) -> str:
    total_ms = int(max(0.0, seconds) * 1000)
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def build_srt(scenes: List[SceneAudio], out_path: Path) -> Path:
    lines = []
    offset = 0.0
    index = 1

    for scene in scenes:
        cues = scene.cues
        for i in range(0, len(cues), WORDS_PER_CAPTION):
            group = cues[i : i + WORDS_PER_CAPTION]
            if not group:
                continue
            # Clamp to this scene's real duration so a mistimed cue can never
            # bleed a caption into the next scene (or the outro bumper).
            start = offset + min(group[0].start, scene.duration)
            end = offset + min(group[-1].end, scene.duration)
            text = " ".join(c.text for c in group)
            lines.append(str(index))
            lines.append(f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}")
            lines.append(text)
            lines.append("")
            index += 1
        offset += scene.duration

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
