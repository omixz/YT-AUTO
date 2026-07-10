"""Text-to-speech narration via Microsoft Edge's free neural voices (edge-tts).

Each scene is synthesized to its own audio file so the assembler knows exactly
how long to hold that scene's visuals for, and word-boundary timestamps are
kept so subtitles.py can burn in captions that track the voiceover.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import edge_tts

from .config import VoiceConfig
from .script_writer import Script


@dataclass
class WordCue:
    text: str
    start: float  # seconds, relative to this scene's audio
    end: float


@dataclass
class SceneAudio:
    scene_index: int
    audio_path: Path
    duration: float
    cues: List[WordCue]


async def _synthesize_one(text: str, voice: VoiceConfig, out_path: Path) -> List[WordCue]:
    communicate = edge_tts.Communicate(
        text, voice.name, rate=voice.rate, pitch=voice.pitch, boundary="WordBoundary"
    )
    cues: List[WordCue] = []
    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 10_000_000  # 100-ns units -> seconds
                cues.append(
                    WordCue(
                        text=chunk["text"],
                        start=start,
                        end=start + chunk["duration"] / 10_000_000,
                    )
                )
    return cues


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def synthesize_script(script: Script, voice: VoiceConfig, work_dir: Path) -> Tuple[List[SceneAudio], Path]:
    """Synthesize every scene's narration, returning per-scene audio and a
    single concatenated narration track for the final mix."""
    work_dir.mkdir(parents=True, exist_ok=True)
    scenes: List[SceneAudio] = []

    for i, scene in enumerate(script.scenes):
        out_path = work_dir / f"scene_{i:02d}.mp3"
        cues = asyncio.run(_synthesize_one(scene.narration, voice, out_path))
        duration = _probe_duration(out_path)
        scenes.append(SceneAudio(scene_index=i, audio_path=out_path, duration=duration, cues=cues))

    # Decode-and-reconcatenate (rather than stream-copy concat) so per-file mp3
    # encoder padding doesn't accumulate into audible drift across scenes.
    full_narration = work_dir / "narration_full.mp3"
    inputs = []
    for s in scenes:
        inputs += ["-i", str(s.audio_path)]
    filter_inputs = "".join(f"[{i}:a]" for i in range(len(scenes)))
    filter_complex = f"{filter_inputs}concat=n={len(scenes)}:v=0:a=1[out]"
    subprocess.run(
        [
            "ffmpeg", "-y", *inputs,
            "-filter_complex", filter_complex, "-map", "[out]",
            str(full_narration),
        ],
        check=True, capture_output=True,
    )

    return scenes, full_narration
