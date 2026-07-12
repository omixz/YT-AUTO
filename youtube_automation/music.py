"""Procedurally synthesized ambient background-music bed.

We can't ship copyrighted music and won't pull tracks from the web, so - the
same philosophy as sound_effects.py - the bed is synthesized from scratch:
a slow, consonant chord pad (a simple Am-F-C-G loop) at low volume, meant to
sit under narration as warmth, not to be noticed. assembler.py mixes it in at
config.video.music_volume_db and loops/truncates to the video length, so this
just needs to produce a pleasant, non-clipping, seam-tolerant loop.
"""
from __future__ import annotations

import wave
from pathlib import Path

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


def build_music_bed(duration: float, work_dir: Path, filename: str = "music_bed.wav") -> Path:
    """Renders a background-music WAV at least `duration` seconds long."""
    segments = []
    filled = 0.0
    i = 0
    while filled < duration:
        chord = _PROGRESSION[i % len(_PROGRESSION)]
        seg_dur = min(_CHORD_SECONDS, duration - filled)
        # Guard against a zero-length final sliver.
        segments.append(_chord_pad(chord, max(seg_dur, 0.05)))
        filled += seg_dur
        i += 1

    bed = np.concatenate(segments) if segments else np.zeros(1)

    # Slow global tremolo for a little life, then normalise well below clipping.
    t = np.linspace(0, len(bed) / SAMPLE_RATE, len(bed), endpoint=False)
    bed = bed * (0.9 + 0.1 * np.sin(2 * np.pi * 0.05 * t))
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
