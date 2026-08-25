"""Stitches per-scene visuals + narration + captions into the final MP4 via ffmpeg.

For each scene: video clips (stock footage, or animation.py's prerendered
longform clips) are scaled/cropped to fill the frame and looped if shorter
than the narration; still images get a role-aware Ken Burns zoom (faster for
hooks, standard for build scenes, slower/gentler for insights). Segments are
crossfaded together (smooth dissolve transitions instead of jarring hard
cuts), captions are burned in, and the narration (plus optional ducked
background music with a dynamic volume envelope and/or a scene-matched
ambience track from sound_effects.py) is muxed on top.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

from .config import PipelineConfig
from .fonts import ASSETS_DIR
from .tts import SceneAudio
from .visuals import VisualAsset

# Scene-role-aware Ken Burns: hook scenes get faster, punchier zoom to match
# their urgency; build scenes use the standard pace; insight scenes slow down
# for a contemplative feel.  These numbers drive zoompan's zoom-step-per-frame
# and maximum zoom factor so consecutive scenes have visually distinct energy
# levels instead of all drifting at the same monotonous crawl.
_ROLE_ZOOM = {
    "hook":    {"step": 0.003,  "max": 1.4},
    "build":   {"step": 0.0015, "max": 1.3},
    "insight": {"step": 0.001,  "max": 1.2},
}
_DEFAULT_ZOOM = _ROLE_ZOOM["build"]

# Default crossfade (dissolve) duration in seconds between scene segments.
CROSSFADE_DEFAULT = 0.4


def run_ffmpeg(cmd: List[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg command failed:\n{' '.join(cmd)}\n\n{result.stderr[-4000:]}")


def build_video_segment(
    asset: VisualAsset, duration: float, config: PipelineConfig, out_path: Path,
    scene_role: str = "build",
) -> None:
    w, h = config.video.resolution
    fps = config.video.fps

    if asset.kind in ("video", "prerendered"):
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", str(asset.path),
            "-t", f"{duration:.3f}",
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},format=yuv420p",
            "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out_path),
        ]
    else:  # image: scene-role-aware Ken Burns zoom
        role_params = _ROLE_ZOOM.get(scene_role, _DEFAULT_ZOOM)
        zoom_step = role_params["step"]
        max_zoom = role_params["max"]
        frames = max(1, round(duration * fps))
        zoom_expr = f"min(zoom+{zoom_step},{max_zoom})"
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
    """Hard-cut concat (fallback when crossfade is impossible)."""
    list_file = work_dir / "video_concat.txt"
    list_file.write_text(
        "\n".join(f"file '{p.name}'" for p in segment_paths), encoding="utf-8"
    )
    run_ffmpeg([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file), "-c", "copy", str(out_path),
    ])


def _crossfade_segments(
    segment_paths: List[Path],
    durations: List[float],
    crossfade: float,
    out_path: Path,
    work_dir: Path,
) -> None:
    """Chain segments with ffmpeg xfade (smooth dissolve) transitions instead
    of hard cuts.  Each adjacent pair of scenes blends over `crossfade`
    seconds, making scene changes feel like deliberate, polished edits
    instead of jarring jumps - the single biggest visual-quality gap between
    a faceless slideshow and a genuinely produced mini-documentary.

    Segments must already be padded (each rendered at natural_duration +
    crossfade, except the last) so xfade has enough overlap content.

    Falls back to hard-cut concat on failure (very short segments, or ffmpeg
    builds without xfade support)."""
    n = len(segment_paths)
    if n <= 1:
        if n == 1:
            import shutil
            shutil.copy2(str(segment_paths[0]), str(out_path))
        return

    # Clamp crossfade so neither adjacent segment is shorter than 2.5x the
    # transition - otherwise xfade produces visually meaningless mush.
    effective = crossfade
    for i in range(n - 1):
        pair_min = min(durations[i], durations[i + 1])
        effective = min(effective, pair_min * 0.35)
    effective = max(0.0, effective)

    if effective <= 0.05:
        _concat_segments(segment_paths, out_path, work_dir)
        return

    # Build the xfade filter chain.  offset_k = sum(d_1..d_k) where d_k is
    # the *natural* (unpadded) duration of segment k.
    inputs: List[str] = []
    for p in segment_paths:
        inputs += ["-i", str(p)]

    filter_parts: List[str] = []
    cumulative = 0.0
    prev_label = "0:v"
    for i in range(n - 1):
        cumulative += durations[i]
        next_idx = i + 1
        out_label = "vout" if i == n - 2 else f"v{i}"
        filter_parts.append(
            f"[{prev_label}][{next_idx}:v]xfade=transition=fade"
            f":duration={effective:.3f}:offset={cumulative:.3f}[{out_label}]"
        )
        prev_label = out_label

    filter_complex = ";".join(filter_parts)
    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    try:
        run_ffmpeg(cmd)
    except RuntimeError:
        _concat_segments(segment_paths, out_path, work_dir)


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
    transitions_path: Optional[Path] = None,
    scene_roles: Optional[List[str]] = None,
    crossfade_duration: float = CROSSFADE_DEFAULT,
) -> Path:
    if len(visuals) != len(scene_audio):
        raise ValueError("visuals and scene_audio must be the same length (one per scene)")

    if scene_roles is None:
        scene_roles = ["build"] * len(visuals)

    segment_paths = []
    natural_durations: List[float] = []
    for i, (asset, audio) in enumerate(zip(visuals, scene_audio)):
        role = scene_roles[i] if i < len(scene_roles) else "build"
        # Pad each segment (except the last) by crossfade_duration so xfade
        # has enough overlap content without shortening the final output.
        extra = crossfade_duration if i < len(visuals) - 1 else 0.0
        seg_path = work_dir / f"segment_{i:02d}.mp4"
        build_video_segment(asset, audio.duration + extra, config, seg_path, scene_role=role)
        segment_paths.append(seg_path)
        natural_durations.append(audio.duration)

    video_concat = work_dir / "video_full.mp4"
    _crossfade_segments(segment_paths, natural_durations, crossfade_duration, video_concat, work_dir)

    burned = work_dir / "video_captioned.mp4"
    if subtitles_path.exists() and subtitles_path.stat().st_size > 0:
        # subtitles_path is an .ass file (subtitles.build_ass) - it carries
        # its own Style block (font, size, karaoke highlight colours), so no
        # force_style override is needed here, just fontsdir so libass can
        # resolve the bundled "Outfit" family instead of falling back to
        # whatever generic default font the runner has installed.
        run_ffmpeg([
            "ffmpeg", "-y", "-i", str(video_concat),
            "-vf", f"subtitles={_escape_for_filter(subtitles_path)}:fontsdir={_escape_for_filter(ASSETS_DIR)}",
            # This is the last video encode before the final mux (which copies
            # the video stream unchanged), so it's worth a slower/better preset
            # than the per-scene intermediate passes above.
            "-c:v", "libx264", "-preset", "faster", "-pix_fmt", "yuv420p", str(burned),
        ])
    else:
        # No cues to burn in (e.g. a scene with no word-boundary data) - an
        # empty subtitle file makes ffmpeg's subtitles filter fail outright,
        # so skip it.
        burned = video_concat

    # Layer narration with any of the optional background audio beds - music
    # and/or the scene-matched ambience track (see sound_effects.py) - via a
    # variable-arity amix, rather than hardcoding for exactly one extra layer.
    # Sidechain compression: duck music/ambience when narration is present.
    # This uses ffmpeg's sidechaincompress filter - the narration (input 1)
    # acts as the control signal to compress the music/ambience beds.
    inputs = ["-i", str(burned), "-i", str(narration_path)]
    filter_parts = []
    audio_labels = ["[1:a]"]  # narration stays at full volume, no processing
    next_input_idx = 2

    if background_music and background_music.exists():
        inputs += ["-stream_loop", "-1", "-i", str(background_music)]
        # Sidechain compress music with narration as control
        # threshold: -24dB - start compressing when narration exceeds this
        # ratio: 4:1 - moderate compression
        # attack: 10ms - fast attack for speech transients
        # release: 200ms - smooth release
        filter_parts.append(
            f"[{next_input_idx}:a][1:a]sidechaincompress="
            f"threshold=-24dB:ratio=4:attack=10:release=200:makeup=1[music]"
        )
        audio_labels.append("[music]")
        next_input_idx += 1

    if ambience_path and ambience_path.exists():
        inputs += ["-i", str(ambience_path)]
        # Sidechain compress ambience more aggressively (it's quieter texture)
        filter_parts.append(
            f"[{next_input_idx}:a][1:a]sidechaincompress="
            f"threshold=-30dB:ratio=6:attack=5:release=300:makeup=1[amb]"
        )
        audio_labels.append("[amb]")
        next_input_idx += 1

    if transitions_path and transitions_path.exists():
        inputs += ["-i", str(transitions_path)]
        # Transitions are brief effects - no sidechain needed, just mix at low level
        filter_parts.append(f"[{next_input_idx}:a]volume=-12dB[trans]")
        audio_labels.append("[trans]")
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
