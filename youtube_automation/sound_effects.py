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

import re
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


def _synth_clash(duration: float) -> np.ndarray:
    """Sword-clash / punch-impact texture for personal fight/duel/brawl
    scenes - distinct from _synth_battle's distant artillery booms. Sparse
    sharp transients (a short high-frequency metallic ring, or a lower
    noise-burst thud) scattered over a quiet noise bed, so it reads as a
    scuffle rather than one clean isolated hit."""
    base = _lowpass(_white_noise(duration), 300) * 0.12
    n = len(base)
    rng = np.random.default_rng(6)
    out = base.copy()
    t = 0.0
    while t < duration:
        pos = int(t * SAMPLE_RATE)
        if rng.random() < 0.5:
            ring_len = int(0.18 * SAMPLE_RATE)
            freq = rng.uniform(1800, 3200)
            tt = np.linspace(0, ring_len / SAMPLE_RATE, ring_len)
            hit = np.sin(2 * np.pi * freq * tt) * np.exp(-tt * 18) * 0.5
            transient = rng.uniform(-1, 1, min(200, ring_len)) * 0.3
            hit[: len(transient)] += transient
        else:
            thud_len = int(0.12 * SAMPLE_RATE)
            hit = _lowpass(rng.uniform(-1, 1, thud_len), 10) * np.linspace(1, 0, thud_len) * 0.6
        end = min(n, pos + len(hit))
        out[pos:end] += hit[: end - pos]
        t += rng.uniform(0.25, 0.55)
    return np.clip(out, -1, 1)


def _synth_crowd(duration: float) -> np.ndarray:
    """'Walla' crowd murmur: several band-passed noise voices in the rough
    speech range, each independently amplitude-modulated at a slow random
    rate, summed together - the standard trick for a plausible background
    chatter bed without needing real recorded voices."""
    n = max(1, int(duration * SAMPLE_RATE))
    out = np.zeros(n)
    rng = np.random.default_rng(7)
    t = np.linspace(0, duration, n)
    for i in range(6):
        voice = _lowpass(_white_noise(duration, seed=100 + i), int(rng.integers(15, 35)))
        mod = 0.5 + 0.5 * np.sin(2 * np.pi * rng.uniform(0.5, 1.4) * t + rng.uniform(0, 6.28))
        out += voice * mod
    return np.clip(out / 6 * 0.35, -1, 1)


def _synth_farm(duration: float) -> np.ndarray:
    return _synth_wind(duration) * 0.5 + _synth_birds(duration)


def _synth_air(duration: float) -> np.ndarray:
    """A neutral, barely-there room-tone/air bed. Used as the default when a
    scene matches no specific atmosphere, so every video still has a quiet
    ambient layer rather than dead silence under the narration."""
    noise = _lowpass(_white_noise(duration), 400)
    t = np.linspace(0, duration, len(noise))
    drift = 0.7 + 0.3 * np.sin(2 * np.pi * 0.05 * t)
    # 0.34, not the original 0.18: every matched bed above sits in the
    # ~0.35-0.6 internal-amplitude range before the *same* flat
    # config.video.sfx_volume_db offset is applied in assembler.py. At 0.18
    # this filler ended up ~15dB quieter than a real match on top of that
    # shared offset - i.e. inaudible - which is why scenes that fell through
    # to it (most human-drama scenes, historically) read as "no sound
    # effects" even though the code was technically always adding something.
    return noise * drift * 0.34


def _synth_tension(duration: float) -> np.ndarray:
    """Low sustained drone with a slow swell, plus an occasional short sting
    - the suspense/reveal bed for assassination/political-plot and "twist"
    moments, which otherwise had no atmosphere of their own and fell through
    to the neutral air bed despite these niches leaning heavily on dramatic
    reveals."""
    n = max(1, int(duration * SAMPLE_RATE))
    t = np.linspace(0, duration, n)
    drone = np.sin(2 * np.pi * 55 * t) * 0.25 + np.sin(2 * np.pi * 82.5 * t) * 0.12
    swell = 0.6 + 0.4 * np.sin(2 * np.pi * 0.08 * t)
    out = drone * swell
    rng = np.random.default_rng(8)
    if duration > 2.0 and rng.random() < 0.6:
        sting_len = min(int(0.5 * SAMPLE_RATE), max(1, n - 1))
        pos = int(rng.uniform(0.3, 0.8) * n)
        tt = np.linspace(0, sting_len / SAMPLE_RATE, sting_len)
        sting = np.sin(2 * np.pi * 220 * tt) * np.exp(-tt * 3) * 0.5
        end = min(n, pos + sting_len)
        out[pos:end] += sting[: end - pos]
    return np.clip(out, -1, 1)


def _synth_celebration(duration: float) -> np.ndarray:
    """Cheering/applause bed for coronations, victories, and parades -
    brighter and busier than the plain crowd murmur, since "the crowd
    roared" reads flat with the same restrained walla used for a quiet
    court scene."""
    n = max(1, int(duration * SAMPLE_RATE))
    out = np.zeros(n)
    rng = np.random.default_rng(9)
    t = np.linspace(0, duration, n)
    for i in range(8):
        voice = _lowpass(_white_noise(duration, seed=200 + i), int(rng.integers(6, 16)))
        mod = 0.5 + 0.5 * np.sin(2 * np.pi * rng.uniform(0.8, 2.2) * t + rng.uniform(0, 6.28))
        out += voice * mod
    out = out / 8 * 0.45
    n_claps = int(duration * 3)
    for _ in range(n_claps):
        clap_len = min(int(0.03 * SAMPLE_RATE), max(1, n - 1))
        pos = int(rng.integers(0, max(1, n - clap_len)))
        clap = rng.uniform(-1, 1, clap_len) * np.linspace(1, 0, clap_len)
        out[pos:pos + clap_len] += clap * 0.3
    return np.clip(out, -1, 1)


def _synth_dungeon_echo(duration: float) -> np.ndarray:
    """A damp, muffled cell ambience - low rumble plus an occasional
    resonant water drip - for prison/captivity scenes."""
    base = _lowpass(_white_noise(duration), 350) * 0.22
    n = len(base)
    rng = np.random.default_rng(10)
    out = base.copy()
    t = 0.0
    while t < duration:
        pos = int(t * SAMPLE_RATE)
        drip_len = min(int(0.4 * SAMPLE_RATE), max(1, n - 1))
        tt = np.linspace(0, drip_len / SAMPLE_RATE, drip_len)
        drip = np.sin(2 * np.pi * 900 * tt) * np.exp(-tt * 9) * 0.35
        end = min(n, pos + drip_len)
        out[pos:end] += drip[: end - pos]
        t += rng.uniform(1.5, 3.5)
    return np.clip(out, -1, 1)


def _synth_radio(duration: float) -> np.ndarray:
    """Crackly radio/telegraph static with occasional short tone blips - for
    WWI/WWII communications scenes."""
    noise = _white_noise(duration)
    hiss = noise - _lowpass(noise, 30)  # crude high-pass via subtracting a low-pass copy
    out = np.clip(hiss * 0.3, -1, 1)
    n = len(out)
    rng = np.random.default_rng(11)
    t = 0.0
    while t < duration:
        pos = int(t * SAMPLE_RATE)
        blip_len = min(int(rng.uniform(0.05, 0.15) * SAMPLE_RATE), max(1, n - 1))
        tt = np.linspace(0, blip_len / SAMPLE_RATE, blip_len)
        blip = np.sin(2 * np.pi * rng.uniform(600, 1200) * tt) * 0.25
        end = min(n, pos + blip_len)
        out[pos:end] += blip[: end - pos]
        t += rng.uniform(0.4, 1.2)
    return np.clip(out, -1, 1)


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
    "clash": _synth_clash,
    "crowd": _synth_crowd,
    "tension": _synth_tension,
    "celebration": _synth_celebration,
    "dungeon_echo": _synth_dungeon_echo,
    "radio": _synth_radio,
    "air": _synth_air,
}

_KEYWORD_TO_SFX: List[Tuple[Tuple[str, ...], str]] = [
    (("rain", "storm", "downpour", "monsoon", "rainstorm"), "rain"),
    (("thunder", "lightning", "thunderstorm"), "thunder"),
    (("fire", "flame", "burning", "blaze", "campfire", "wildfire"), "fire"),
    (("horse", "cavalry", "stable", "hooves", "galloping"), "horse"),
    (("farm", "crop", "harvest", "barn", "countryside", "plowing", "planting", "field"), "farm"),
    (("ocean", "sea", "wave", "beach", "coast", "shore", "tide"), "ocean"),
    # Personal fight/duel/brawl gets a clash/impact texture; large-scale war
    # keeps the distant-boom "battle" bed - checked first since e.g. "sword
    # fight" would otherwise also match nothing more specific.
    (("duel", "sword fight", "swordfight", "brawl", "melee", "fistfight", "fist fight",
      "wrestl", "sparring", "clashed swords", "grappl"), "clash"),
    (("battle", "war", "combat", "explosion", "artillery", "gunfire"), "battle"),
    # Assassination/political-plot and dramatic "twist" reveals - previously
    # unmatched entirely, despite being a large share of dark_history/
    # modern_history/unsolved_mysteries content, whose tone (config.yaml:
    # "dramatic, high-stakes, suspenseful") this bed is built for.
    (("assassinat", "conspiracy", "conspired", "plotted", "coup", "betrayal", "betrayed",
      "twist", "revealed the truth", "shocking truth", "secret plan"), "tension"),
    # Coronation/celebration/victory - previously fell through to nothing
    # despite being common in ancient_civilizations/world_wars payoff scenes.
    (("coronation", "crowned", "celebrat", "victory", "triumph", "parade",
      "cheered", "cheering", "applause", "hailed"), "celebration"),
    # Prison/captivity - shares its keyword set with procedural_illustration's
    # "dungeon" visual setting for the same reason: a captivity scene is
    # neither the generic indoor office/lab sound nor silence.
    (("dungeon", "prison", "imprisoned", "captive", "shackled", "incarcerated",
      "jailed", "chained", "chains"), "dungeon_echo"),
    # Telegraph/radio communications - common in world_wars/modern_history.
    (("telegraph", "radio", "wireless", "transmission", "broadcast",
      "morse code", "signal corps", "wire service"), "radio"),
    (("court", "courtiers", "marketplace", "town square", "gathered crowd", "spectators",
      "onlookers", "murmur", "chatter", "assembly hall",
      "trial", "tribunal", "verdict", "testify", "witness stand"), "crowd"),
    (("forest", "jungle", "wilderness", "nature", "woods"), "birds"),
    (("wind", "gale", "blizzard"), "wind"),
]


def _contains_keyword(haystack: str, keyword: str) -> bool:
    """Word-boundary-aware match for single-word keywords; plain substring
    match for multi-word phrases (which are collision-safe on their own).
    Needed now that the haystack includes full narration, not just short
    visual-keyword tags: bare substring matching let "field" (farm) match
    "battlefield", misrouting a war scene's ambience to farm sounds - see
    the identical fix (and rationale) in procedural_illustration.py."""
    if " " in keyword or "-" in keyword:
        return keyword in haystack
    return re.search(rf"\b{re.escape(keyword)}(?:es|s)?\b", haystack) is not None


def sfx_for_scene(scene: Scene) -> Optional[str]:
    haystack = f"{scene.narration} {' '.join(scene.visual_keywords)}".lower()
    for keywords, name in _KEYWORD_TO_SFX:
        if any(_contains_keyword(haystack, kw) for kw in keywords):
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
    outro): each content scene gets either its keyword-matched SFX or the
    neutral air bed, so the track is always present - every video has an
    ambient layer, never dead silence under the narration."""
    total_duration = intro_duration + sum(a.duration for a in content_scene_audio) + outro_duration
    track = np.zeros(max(1, int(total_duration * SAMPLE_RATE)))
    matched_any = False

    offset = intro_duration
    for scene, audio in zip(scenes, content_scene_audio):
        # A scene with no specific atmosphere still gets the neutral air bed,
        # so every video has an ambient layer (guaranteed, never silent) -
        # matched scenes just layer their specific SFX on top of that.
        name = sfx_for_scene(scene)
        if name:
            matched_any = True
        samples = _fade(_SFX_SYNTH[name or "air"](audio.duration))
        start = int(offset * SAMPLE_RATE)
        end = min(len(track), start + len(samples))
        track[start:end] += samples[: end - start]
        offset += audio.duration

    out_path = work_dir / "ambience.wav"
    _write_wav(track, out_path)
    return out_path
