"""Stitches per-scene visuals + narration + captions into the final MP4 via ffmpeg.

For each scene: video clips (stock footage, or animation.py's prerendered
longform clips) are scaled/cropped to fill the frame and looped if shorter
than the narration; still images get a slow Ken Burns zoom. Segments are
concatenated, captions are burned in, and the narration (plus optional
ducked background music) is muxed on top.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

from .config import PipelineConfig
from .tts import SceneAudio
from .visuals import VisualAsset

MIN_ZOOM_STEP = 0.0015
MAX_ZOOM = 1.3


def _run(cmd: List[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg command failed:\n{' '.join(cmd)}\n\n{result.stderr[-4000:]}")


def _build_video_segment(asset: VisualAsset, duration: float, config: PipelineConfig, out_path: Path) -> None:
    w, h = config.video.resolution
    fps = config.video.fps

    if asset.kind in ("video", "prerendered"):
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", str(asset.path),
            "-t", f"{duration:.3f}",
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},format=yuv420p",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_path),
        ]
    else:  # image: Ken Burns zoom
        frames = max(1, round(duration * fps))
        zoom_expr = f"min(zoom+{MIN_ZOOM_STEP},{MAX_ZOOM})"
        vf = (
            f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,"
            f"crop={w*2}:{h*2},"
            f"zoompan=z='{zoom_expr}':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps},"
            f"format=yuv420p"
        )
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", str(asset.path),
            "-t", f"{duration:.3f}", "-vf", vf,
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_path),
        ]

    _run(cmd)


def _concat_segments(segment_paths: List[Path], out_path: Path, work_dir: Path) -> None:
    list_file = work_dir / "video_concat.txt"
    list_file.write_text(
        "\n".join(f"file '{p.name}'" for p in segment_paths), encoding="utf-8"
    )
    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file), "-c", "copy", str(out_path),
    ])


def _escape_for_filter(path: Path) -> str:
    # ffmpeg filtergraph string args need colons and backslashes escaped.
    return str(path).replace("\\", "\\\\").replace(":", "\\:")


def build_video(
    visuals: List[VisualAsset],
    scene_audio: List[SceneAudio],
    narration_path: Path,
    subtitles_path: Path,
    config: PipelineConfig,
    work_dir: Path,
    out_path: Path,
    background_music: Optional[Path] = None,
) -> Path:
    if len(visuals) != len(scene_audio):
        raise ValueError("visuals and scene_audio must be the same length (one per scene)")

    segment_paths = []
    for i, (asset, audio) in enumerate(zip(visuals, scene_audio)):
        seg_path = work_dir / f"segment_{i:02d}.mp4"
        _build_video_segment(asset, audio.duration, config, seg_path)
        segment_paths.append(seg_path)

    video_concat = work_dir / "video_full.mp4"
    _concat_segments(segment_paths, video_concat, work_dir)

    burned = work_dir / "video_captioned.mp4"
    if subtitles_path.exists() and subtitles_path.stat().st_size > 0:
        subs_style = "FontSize=16,Alignment=2,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,MarginV=80"
        _run([
            "ffmpeg", "-y", "-i", str(video_concat),
            "-vf", f"subtitles={_escape_for_filter(subtitles_path)}:force_style='{subs_style}'",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(burned),
        ])
    else:
        # No cues to burn in (e.g. a scene with no word-boundary data) - an
        # empty SRT makes ffmpeg's subtitles filter fail outright, so skip it.
        burned = video_concat

    if background_music and background_music.exists():
        music_gain = config.video.music_volume_db
        cmd = [
            "ffmpeg", "-y",
            "-i", str(burned),
            "-i", str(narration_path),
            "-stream_loop", "-1", "-i", str(background_music),
            "-filter_complex",
            f"[2:a]volume={music_gain}dB[music];[1:a][music]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-shortest", str(out_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(burned),
            "-i", str(narration_path),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-shortest", str(out_path),
        ]

    _run(cmd)
    return out_path
