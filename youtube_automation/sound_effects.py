"""Procedurally synthesized ambient sound effects (rain, fire, horses, crowds,
farm ambience, ...) layered quietly under narration for scenes whose visual
keywords suggest a matching atmosphere - no external SFX library or API key
needed, just basic noise-shaping DSP with numpy.

Deliberately background-only: these are meant to sit under narration/music at
low volume as texture, not to be sound design in their own right. A handful
of categories (crowd murmur, "children playing") are hard to fake believably
from noise alone, so keywords that would need those are simply left unmatched
rather than shipping something that sounds obviously synthetic.
"""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from .script_writer import Scene
from .tts import SceneAudio

SAMPLE_RATE = 44100


def _white_noise(duration: float, seed: Optional[int] = None) -> np.ndarray:
    n = max(1, int(duration * SAMPLE_RATE))
    rng = np.random.default_rng(seed)
    return rng.uniform(-1.0, 1.0, n)


def _lowpass(signal: np.ndarray, window: int) -> np.ndarray:
    """Cheap box-filter low-pass (no scipy dependency) - turns harsh white
    noise into something closer to hiss/rumble depending on window size."""
    if window <= 1 or len(signal) < 2:
        return signal
    kernel = np.ones(window) / window
    return np.convolve(signal, kernel, mode="same")


def _fade(samples: np.ndarray, seconds: float = 0.35) -> np.ndarray:
    n = len(samples)
    fade_n = min(int(seconds * SAMPLE_RATE), n // 2)
    if fade_n <= 0:
        return samples
    env = np.ones(n)
    env[:fade_n] = np.linspace(0.0, 1.0, fade_n)
    env[-fade_n:] = np.linspace(1.0, 0.0, fade_n)
    return samples * env


# --- synthesis -------------------------------------------------------------

def _synth_rain(duration: float) -> np.ndarray:
    noise = _lowpass(_white_noise(duration), 6)
    t = np.linspace(0, duration, len(noise))
    gust = 0.85 + 0.15 * np.sin(2 * np.pi * 0.07 * t)
    return noise * gust * 0.5


def _synth_wind(duration: float) -> np.ndarray:
    noise = _lowpass(_white_noise(duration), 200)
    t = np.linspace(0, duration, len(noise))
    gust = 0.6 + 0.4 * np.sin(2 * np.pi * 0.15 * t) * np.sin(2 * np.pi * 0.03 * t + 1)
    return noise * gust * 0.6


def _synth_fire(duration: float) -> np.ndarray:
    base = _lowpass(_white_noise(duration), 40) * 0.35
    n = len(base)
    rng = np.random.default_rng(1)
    crackle = np.zeros(n)
    for _ in range(int(duration * 6)):
        pop_len = int(rng.integers(20, 120))
        pos = int(rng.integers(0, max(1, n - pop_len)))
        pop = rng.uniform(-1, 1, pop_len) * np.linspace(1, 0, pop_len)
        crackle[pos:pos + pop_len] += pop
    return np.clip(base + crackle * 0.4, -1, 1)


def _synth_ocean(duration: float) -> np.ndarray:
    noise = _lowpass(_white_noise(duration), 120)
    t = np.linspace(0, duration, len(noise))
    swell = (np.sin(2 * np.pi * 0.09 * t) * 0.5 + 0.5) ** 1.5
    return noise * swell * 0.55


def _synth_horse(duration: float) -> np.ndarray:
    n = max(1, int(duration * SAMPLE_RATE))
    out = np.zeros(n)
    rng = np.random.default_rng(2)
    t = 0.0
    while t < duration:
        pos = int(t * SAMPLE_RATE)
        thud_len = int(0.05 * SAMPLE_RATE)
        thud = _lowpass(rng.uniform(-1, 1, thud_len), 8) * np.linspace(1, 0, thud_len)
        end = min(n, pos + thud_len)
        out[pos:end] += thud[: end - pos] * 0.6
        t += 0.28 * rng.uniform(0.9, 1.1)
    return out


def _synth_birds(duration: float) -> np.ndarray:
    n = max(1, int(duration * SAMPLE_RATE))
    out = np.zeros(n)
    rng = np.random.default_rng(3)
    t = 0.0
    while t < duration:
        pos = int(t * SAMPLE_RATE)
        chirp_len = int(rng.uniform(0.08, 0.18) * SAMPLE_RATE)
        freq_sweep = np.linspace(rng.uniform(1800, 3000), rng.uniform(2500, 4200), chirp_len)
        chirp = np.sin(2 * np.pi * np.cumsum(freq_sweep) / SAMPLE_RATE) * np.hanning(chirp_len)
        end = min(n, pos + chirp_len)
        out[pos:end] += chirp[: end - pos] * 0.25
        t += rng.uniform(0.6, 2.2)
    return out


def _synth_thunder(duration: float) -> np.ndarray:
    out = _lowpass(_white_noise(duration), 300) * 0.2
    n = len(out)
    rng = np.random.default_rng(4)
    for _ in range(max(1, int(duration / 4))):
        # Clamped to the clip length - on a very short scene an unclamped
        # burst could run past the end of `out`, and a += between mismatched
        # shapes raises rather than silently truncating.
        clap_len = min(int(rng.uniform(0.6, 1.4) * SAMPLE_RATE), max(1, n - 1))
        pos = int(rng.integers(0, max(1, n - clap_len)))
        clap = _lowpass(rng.uniform(-1, 1, clap_len), 30) * np.linspace(1, 0.1, clap_len) ** 2
        out[pos:pos + clap_len] += clap * 0.7
    return np.clip(out, -1, 1)


def _synth_battle(duration: float) -> np.ndarray:
    base = _lowpass(_white_noise(duration), 250) * 0.25
    n = len(base)
    rng = np.random.default_rng(5)
    booms = np.zeros(n)
    for _ in range(max(1, int(duration / 3))):
        boom_len = min(int(rng.uniform(0.3, 0.6) * SAMPLE_RATE), max(1, n - 1))
        pos = int(rng.integers(0, max(1, n - boom_len)))
        boom = _lowpass(rng.uniform(-1, 1, boom_len), 60) * np.linspace(1, 0, boom_len)
        booms[pos:pos + boom_len] += boom
    return np.clip(base + booms * 0.5, -1, 1)


def _synth_farm(duration: float) -> np.ndarray:
    return _synth_wind(duration) * 0.5 + _synth_birds(duration)


_SFX_SYNTH: Dict[str, Callable[[float], np.ndarray]] = {
    "rain": _synth_rain,
    "thunder": _synth_thunder,
    "fire": _synth_fire,
    "wind": _synth_wind,
    "ocean": _synth_ocean,
    "horse": _synth_horse,
    "farm": _synth_farm,
    "birds": _synth_birds,
    "battle": _synth_battle,
}

_KEYWORD_TO_SFX: List[Tuple[Tuple[str, ...], str]] = [
    (("rain", "storm", "downpour", "monsoon", "rainstorm"), "rain"),
    (("thunder", "lightning", "thunderstorm"), "thunder"),
    (("fire", "flame", "burning", "blaze", "campfire", "wildfire"), "fire"),
    (("horse", "cavalry", "stable", "hooves", "galloping"), "horse"),
    (("farm", "crop", "harvest", "barn", "countryside", "plowing", "planting", "field"), "farm"),
    (("ocean", "sea", "wave", "beach", "coast", "shore", "tide"), "ocean"),
    (("battle", "war", "combat", "explosion", "artillery", "gunfire"), "battle"),
    (("forest", "jungle", "wilderness", "nature", "woods"), "birds"),
    (("wind", "gale", "blizzard"), "wind"),
]


def sfx_for_scene(scene: Scene) -> Optional[str]:
    haystack = " ".join(scene.visual_keywords).lower()
    for keywords, name in _KEYWORD_TO_SFX:
        if any(kw in haystack for kw in keywords):
            return name
    return None


# --- track assembly ---------------------------------------------------------

def _write_wav(samples: np.ndarray, path: Path) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(pcm.tobytes())


def build_ambience_track(
    scenes: List[Scene],
    content_scene_audio: List[SceneAudio],
    intro_duration: float,
    outro_duration: float,
    work_dir: Path,
) -> Optional[Path]:
    """Builds one ambience track spanning the whole video (intro + content +
    outro), with each matched content scene's synthesized SFX pasted in at
    that scene's actual time offset. Returns None if nothing matched, so
    callers can skip mixing entirely rather than adding a silent layer."""
    total_duration = intro_duration + sum(a.duration for a in content_scene_audio) + outro_duration
    track = np.zeros(max(1, int(total_duration * SAMPLE_RATE)))
    matched_any = False

    offset = intro_duration
    for scene, audio in zip(scenes, content_scene_audio):
        name = sfx_for_scene(scene)
        if name:
            matched_any = True
            samples = _fade(_SFX_SYNTH[name](audio.duration))
            start = int(offset * SAMPLE_RATE)
            end = min(len(track), start + len(samples))
            track[start:end] += samples[: end - start]
        offset += audio.duration

    if not matched_any:
        return None

    out_path = work_dir / "ambience.wav"
    _write_wav(track, out_path)
    return out_path
