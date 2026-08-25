"""Procedurally synthesized ambient background-music bed.

We can't ship copyrighted music and won't pull tracks from the web, so - the
same philosophy as sound_effects.py - the bed is synthesized from scratch:
a slow, consonant chord pad (a simple Am-F-C-G loop) at low volume, meant to
sit under narration as warmth, not to be noticed. assembler.py mixes it in at
config.video.music_volume_db and loops/truncates to the video length, so this
just needs to produce a pleasant, non-clipping, seam-tolerant loop.

When scene_durations is provided, a dynamic volume envelope is applied so
the music "breathes" with the video: it ducks during the hook's first few
seconds (letting narration land cleanly), swells briefly at each scene
transition (adding energy and marking the shift), and fades out over the
final seconds.
"""
from __future__ import annotations

import wave
from pathlib import Path
from typing import List, Optional

import numpy as np

SAMPLE_RATE = 44100

# A gentle, consonant progression with smooth voice-leading (frequencies in Hz).
# Am - F - C - G, three notes per chord, low in the register for a warm pad.
_PROGRESSION = [
    (220.00, 261.63, 329.63),  # Am
    (174.61, 220.00, 261.63),  # F
    (261.63, 329.63, 392.00),  # C
    (196.00, 246.94, 293.66),  # G
]
_CHORD_SECONDS = 6.0


def _chord_pad(freqs, duration: float) -> np.ndarray:
    n = max(1, int(duration * SAMPLE_RATE))
    t = np.linspace(0, duration, n, endpoint=False)
    voice = np.zeros(n)
    for f in freqs:
        # Fundamental + a quiet octave below for warmth + a soft fifth partial.
        voice += np.sin(2 * np.pi * f * t)
        voice += 0.5 * np.sin(2 * np.pi * (f / 2) * t)
        voice += 0.15 * np.sin(2 * np.pi * (f * 1.5) * t)
    voice /= (len(freqs) * 1.65)

    # Per-chord swell (attack/release) so chords breathe into each other
    # instead of clicking at segment boundaries.
    env = np.ones(n)
    ramp = min(int(1.0 * SAMPLE_RATE), n // 2)
    if ramp > 0:
        env[:ramp] = np.linspace(0.0, 1.0, ramp)
        env[-ramp:] = np.linspace(1.0, 0.0, ramp)
    return voice * env


def _apply_volume_envelope(
    bed: np.ndarray, duration: float, scene_durations: Optional[List[float]],
) -> np.ndarray:
    """Shape the music bed's volume over time so it feels produced instead of
    flat.  Three axes of dynamics:

    1. Hook duck: the first few seconds are quieter (0.6 → 1.0 ramp over 3s)
       so the hook narration lands clearly without fighting the music.
    2. Transition swells: at each scene boundary the volume briefly rises
       (~+15 %) for 0.3 s, marking the visual shift with a subtle energy
       bump that keeps the audio from feeling like wallpaper.
    3. Outro fade: the last 3 s fade to silence so the video doesn't end
       on an abrupt music cut."""
    t = np.linspace(0, duration, len(bed), endpoint=False)
    env = np.ones(len(bed))

    # 1. Hook duck: quiet start, ramp up over 3 s
    hook_ramp = np.clip(t / 3.0, 0.0, 1.0) * 0.4 + 0.6
    env *= hook_ramp

    # 3. Outro fade: last 3 s
    outro_start = max(0.0, duration - 3.0)
    outro_mask = t > outro_start
    if outro_mask.any():
        env[outro_mask] *= np.linspace(1.0, 0.0, int(outro_mask.sum()))

    # 2. Transition swells: Gaussian bump at each scene boundary
    if scene_durations:
        cumulative = 0.0
        for d in scene_durations[:-1]:
            cumulative += d
            gauss = np.exp(-((t - cumulative) ** 2) / (2 * 0.04))
            env *= 1.0 + 0.15 * gauss

    bed *= env
    return bed


def build_music_bed(
    duration: float, work_dir: Path, filename: str = "music_bed.wav",
    scene_durations: Optional[List[float]] = None,
) -> Path:
    """Renders a background-music WAV at least `duration` seconds long."""
    segments = []
    filled = 0.0
    i = 0
    while filled < duration:
        chord = _PROGRESSION[i % len(_PROGRESSION)]
        seg_dur = min(_CHORD_SECONDS, duration - filled)
        segments.append(_chord_pad(chord, max(seg_dur, 0.05)))
        filled += seg_dur
        i += 1

    bed = np.concatenate(segments) if segments else np.zeros(1)

    # Slow global tremolo for a little life, then normalise well below clipping.
    t = np.linspace(0, len(bed) / SAMPLE_RATE, len(bed), endpoint=False)
    bed = bed * (0.9 + 0.1 * np.sin(2 * np.pi * 0.05 * t))

    bed = _apply_volume_envelope(bed, duration, scene_durations)

    peak = np.max(np.abs(bed)) or 1.0
    bed = bed / peak * 0.6

    out_path = work_dir / filename
    pcm = (np.clip(bed, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(out_path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(pcm.tobytes())
    return out_path
