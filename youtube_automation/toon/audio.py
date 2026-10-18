"""Narration loudness -> per-frame mouth openness and 'sentence start' beats.
Free and local: ffmpeg decodes the scene's audio, numpy does the rest."""
from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import List, Optional

import numpy as np


def synthetic_envelope(n: int, fps: int, seed: int = 0) -> np.ndarray:
    """Plausible talking pattern (syllable bursts with pauses) for when there is no audio."""
    t = np.arange(n) / fps
    syl = np.abs(np.sin(t * math.pi * 3.4 + seed))
    phrase = (np.sin(t * 1.15 + seed * 1.7) > -0.35).astype(float)
    return np.clip(syl * phrase, 0, 1)


def envelope(audio_path: Optional[Path], fps: int, n_frames: int, seed: int = 0) -> np.ndarray:
    """Per-frame loudness in [0, 1]. Falls back to a synthetic pattern if decoding fails."""
    if audio_path is None or not Path(audio_path).exists():
        return synthetic_envelope(n_frames, fps, seed)
    try:
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(audio_path), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
            capture_output=True, check=True, timeout=120).stdout
        pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if pcm.size < 8:
            return synthetic_envelope(n_frames, fps, seed)
        win = max(1, 8000 // fps)
        total = n_frames * win
        pcm = np.pad(pcm, (0, max(0, total - pcm.size)))[:total]
        rms = np.sqrt((pcm.reshape(n_frames, win) ** 2).mean(axis=1))
        ref = np.percentile(rms, 95) or 1.0
        env = np.clip(rms / ref, 0, 1.2)
        env = np.clip(env, 0, 1)
        kernel = np.array([0.25, 0.5, 0.25])
        return np.convolve(env, kernel, mode="same")
    except Exception:
        return synthetic_envelope(n_frames, fps, seed)


def sentence_beats(env: np.ndarray, fps: int, min_gap: float = 0.9) -> List[float]:
    """Times (s) where speech resumes after a pause - the moments to nudge the camera / start a gesture."""
    beats: List[float] = []
    quiet = 0
    last = -min_gap
    for i, v in enumerate(env):
        if v < 0.12:
            quiet += 1
        else:
            if quiet >= int(0.28 * fps) and v > 0.3 and (i / fps - last) >= min_gap:
                beats.append(i / fps)
                last = i / fps
            quiet = 0
    return beats
