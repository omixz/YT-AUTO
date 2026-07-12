"""Cheap heuristic gates that run before upload.

Two phases, since the things worth checking exist at different points in
the pipeline:

- `check()` runs right after the script is written - too few words, too few
  scenes, or missing the hook/insight structure the script prompt was told
  to follow. This is exactly what YouTube's reused/duplicative content
  policy targets, so catching it matters even before anything is rendered.
- `check_media()` runs after the final video is assembled - it actually
  inspects the rendered file (via ffprobe) rather than trusting that every
  upstream step worked, catching the class of bug where a renderer or mixer
  step silently produces something broken: a truncated render, a video with
  no audio track, a mix so quiet it reads as silent, wrong resolution, or
  captions that never actually got word-cue data.

A failing gate (either phase) still gets built and uploaded (never silently
dropped) - it's just uploaded under quality.fallback_privacy_status instead
of the configured public/unlisted default, so a weak or broken episode
doesn't go out unattended and a human can decide by hand.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import List, Tuple

from .config import PipelineConfig
from .script_writer import Script
from .tts import SceneAudio

logger = logging.getLogger(__name__)

# Below this mean_volume (dBFS, from ffmpeg's volumedetect), a mix reads as
# effectively silent or broken rather than just "quiet content" - the
# louder mix landed on earlier this session runs narration alone at roughly
# -13 to -18dB mean, so anything this far under it means a layer (or all of
# them) didn't make it into the final mux.
MIN_MEAN_VOLUME_DB = -40.0

# How far the rendered video's duration is allowed to drift from the sum of
# its scene audio durations before it's flagged as a truncated/corrupted
# render rather than just normal encoder rounding.
MAX_DURATION_DRIFT_FRACTION = 0.10
MAX_DURATION_DRIFT_SECONDS = 5.0


def check(script: Script, config: PipelineConfig) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    q = config.quality

    word_count = len(script.full_narration.split())
    if word_count < q.min_words:
        reasons.append(f"only {word_count} words of narration (min {q.min_words})")

    if len(script.scenes) < q.min_scenes:
        reasons.append(f"only {len(script.scenes)} scenes (min {q.min_scenes})")

    if q.require_hook_and_insight:
        if not script.scenes or script.scenes[0].role != "hook":
            reasons.append("first scene is not role=hook")
        if not script.scenes or script.scenes[-1].role != "insight":
            reasons.append("last scene is not role=insight")

    return (len(reasons) == 0, reasons)


def _ffprobe_streams(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-show_entries", "stream=codec_type,width,height,r_frame_rate",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def _parse_frame_rate(r_frame_rate: "str | None") -> "float | None":
    if not r_frame_rate or "/" not in r_frame_rate:
        return None
    num, _, den = r_frame_rate.partition("/")
    try:
        num, den = float(num), float(den)
        return num / den if den else None
    except ValueError:
        return None


def _mean_volume_db(path: Path) -> "float | None":
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    for line in result.stderr.splitlines():
        if "mean_volume:" in line:
            try:
                return float(line.split("mean_volume:")[1].strip().split(" ")[0])
            except ValueError:
                return None
    return None


def check_media(
    video_path: Path, all_scene_audio: List[SceneAudio], captions_path: "Path | None", config: PipelineConfig,
) -> Tuple[bool, List[str]]:
    """Inspects the actually-rendered final.mp4 (and captions file) rather
    than trusting every upstream step worked - see module docstring."""
    reasons: List[str] = []

    if not video_path.exists() or video_path.stat().st_size == 0:
        return False, ["final video file is missing or empty"]

    probe = _ffprobe_streams(video_path)
    streams = probe.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    if not video_streams:
        reasons.append("rendered file has no video stream")
    else:
        w, h = video_streams[0].get("width"), video_streams[0].get("height")
        expected_w, expected_h = config.video.resolution
        if (w, h) != (expected_w, expected_h):
            reasons.append(f"rendered resolution {w}x{h} doesn't match configured {expected_w}x{expected_h}")

        fps = _parse_frame_rate(video_streams[0].get("r_frame_rate"))
        if fps is None:
            reasons.append("could not determine rendered frame rate")
        elif abs(fps - config.video.fps) > 1.0:
            reasons.append(f"rendered frame rate {fps:.1f}fps doesn't match configured {config.video.fps}fps")

    if not audio_streams:
        reasons.append("rendered file has no audio stream (silent video)")

    expected_duration = sum(a.duration for a in all_scene_audio)
    try:
        actual_duration = float(probe.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        actual_duration = 0.0
    drift = abs(actual_duration - expected_duration)
    if actual_duration <= 0:
        reasons.append("could not determine rendered video duration")
    elif drift > max(MAX_DURATION_DRIFT_SECONDS, expected_duration * MAX_DURATION_DRIFT_FRACTION):
        reasons.append(
            f"rendered duration {actual_duration:.1f}s doesn't match expected {expected_duration:.1f}s "
            f"(drift {drift:.1f}s) - possible truncated/corrupted render"
        )

    if audio_streams:
        mean_db = _mean_volume_db(video_path)
        if mean_db is None:
            reasons.append("could not measure audio loudness")
        elif mean_db < MIN_MEAN_VOLUME_DB:
            reasons.append(f"audio mix is effectively silent (mean_volume={mean_db:.1f}dB, min {MIN_MEAN_VOLUME_DB}dB)")

    if captions_path is not None:
        if not captions_path.exists() or captions_path.stat().st_size == 0:
            reasons.append("captions file is missing or empty")
        elif "Dialogue:" not in captions_path.read_text(encoding="utf-8", errors="ignore"):
            reasons.append("captions file has no caption lines (word-timing data may have failed)")

    if reasons:
        logger.warning("Media quality gate failed: %s", "; ".join(reasons))
    return (len(reasons) == 0, reasons)
