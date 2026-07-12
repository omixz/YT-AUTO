"""Stitches per-scene visuals + narration + captions into the final MP4 via ffmpeg.

For each scene: video clips (stock footage, or animation.py's prerendered
longform clips) are scaled/cropped to fill the frame and looped if shorter
than the narration; still images get a slow Ken Burns zoom. Segments are
concatenated, captions are burned in, and the narration (plus optional
ducked background music and/or a scene-matched ambience track from
sound_effects.py) is muxed on top.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

from .config import PipelineConfig
from .fonts import ASSETS_DIR
from .tts import SceneAudio
from .visuals import VisualAsset

MIN_ZOOM_STEP = 0.0015
MAX_ZOOM = 1.3


def run_ffmpeg(cmd: List[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg command failed:\n{' '.join(cmd)}\n\n{result.stderr[-4000:]}")


def build_video_segment(asset: VisualAsset, duration: float, config: PipelineConfig, out_path: Path) -> None:
    w, h = config.video.resolution
    fps = config.video.fps

    if asset.kind in ("video", "prerendered"):
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", str(asset.path),
            "-t", f"{duration:.3f}",
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},format=yuv420p",
            # ultrafast: this segment gets re-encoded again downstream (colorkey
            # composite for longform, caption burn-in for every format), so
            # spending time on encode efficiency here is pure waste - it matters
            # a lot once a longform video means dozens of these per run.
            "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out_path),
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
            "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out_path),
        ]

    run_ffmpeg(cmd)


def _concat_segments(segment_paths: List[Path], out_path: Path, work_dir: Path) -> None:
    list_file = work_dir / "video_concat.txt"
    list_file.write_text(
        "\n".join(f"file '{p.name}'" for p in segment_paths), encoding="utf-8"
    )
    run_ffmpeg([
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
    ambience_path: Optional[Path] = None,
) -> Path:
    if len(visuals) != len(scene_audio):
        raise ValueError("visuals and scene_audio must be the same length (one per scene)")

    segment_paths = []
    for i, (asset, audio) in enumerate(zip(visuals, scene_audio)):
        seg_path = work_dir / f"segment_{i:02d}.mp4"
        build_video_segment(asset, audio.duration, config, seg_path)
        segment_paths.append(seg_path)

    video_concat = work_dir / "video_full.mp4"
    _concat_segments(segment_paths, video_concat, work_dir)

    burned = work_dir / "video_captioned.mp4"
    if subtitles_path.exists() and subtitles_path.stat().st_size > 0:
        # Fontname=Outfit + fontsdir: without an explicit font, libass falls
        # back to whatever generic default the runner has installed, which
        # reads as dated - use the same modern bundled font as the
        # thumbnail/branding text (see fonts.py) for burned-in captions too.
        subs_style = "Fontname=Outfit,Bold=1,FontSize=16,Alignment=2,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,MarginV=80"
        run_ffmpeg([
            "ffmpeg", "-y", "-i", str(video_concat),
            "-vf", f"subtitles={_escape_for_filter(subtitles_path)}:force_style='{subs_style}':fontsdir={_escape_for_filter(ASSETS_DIR)}",
            # This is the last video encode before the final mux (which copies
            # the video stream unchanged), so it's worth a slower/better preset
            # than the per-scene intermediate passes above.
            "-c:v", "libx264", "-preset", "faster", "-pix_fmt", "yuv420p", str(burned),
        ])
    else:
        # No cues to burn in (e.g. a scene with no word-boundary data) - an
        # empty SRT makes ffmpeg's subtitles filter fail outright, so skip it.
        burned = video_concat

    # Layer narration with any of the optional background audio beds - music
    # and/or the scene-matched ambience track (see sound_effects.py) - via a
    # variable-arity amix, rather than hardcoding for exactly one extra layer.
    inputs = ["-i", str(burned), "-i", str(narration_path)]
    filter_parts = []
    audio_labels = ["[1:a]"]
    next_input_idx = 2

    if background_music and background_music.exists():
        inputs += ["-stream_loop", "-1", "-i", str(background_music)]
        filter_parts.append(f"[{next_input_idx}:a]volume={config.video.music_volume_db}dB[music]")
        audio_labels.append("[music]")
        next_input_idx += 1

    if ambience_path and ambience_path.exists():
        inputs += ["-i", str(ambience_path)]
        filter_parts.append(f"[{next_input_idx}:a]volume={config.video.sfx_volume_db}dB[amb]")
        audio_labels.append("[amb]")
        next_input_idx += 1

    if len(audio_labels) > 1:
        # normalize=0 is essential: amix's default (normalize=1) divides every
        # input - including the narration - by the number of layers, so adding
        # a music + SFX bed would drag the whole mix ~9dB quieter and bury the
        # beds. With normalize off, narration stays at full and the beds sit at
        # exactly the dB offset set by their volume filters above.
        mix_filter = "".join(audio_labels) + f"amix=inputs={len(audio_labels)}:duration=first:dropout_transition=2:normalize=0[aout]"
        filter_complex = ";".join(filter_parts + [mix_filter])
        cmd = [
            "ffmpeg", "-y", *inputs,
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-shortest", str(out_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y", *inputs,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-shortest", str(out_path),
        ]

    run_ffmpeg(cmd)
    return out_path
