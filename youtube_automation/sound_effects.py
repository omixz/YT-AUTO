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
    return noise * drift * 0.18


def _synth_war_ambience(duration: float) -> np.ndarray:
    """Distant battle sounds: horns, drums, shouted commands, horse whinnies, 
    metal clanking, distant explosions. Low volume texture."""
    n = max(1, int(duration * SAMPLE_RATE))
    out = np.zeros(n)
    rng = np.random.default_rng(8)
    t = np.linspace(0, duration, n)
    
    # Low-frequency rumble base
    rumble = _lowpass(_white_noise(duration, seed=8), 500) * 0.1
    
    # Distant horns (low brass)
    horn_count = max(1, int(duration / 15))
    for _ in range(horn_count):
        start = rng.integers(0, max(1, n - int(2 * SAMPLE_RATE)))
        length = min(int(rng.uniform(1.5, 3.0) * SAMPLE_RATE), n - start)
        horn_t = np.linspace(0, length / SAMPLE_RATE, length)
        freq = rng.uniform(80, 150)
        horn = np.sin(2 * np.pi * freq * horn_t) * np.exp(-horn_t * 0.8)
        horn += 0.3 * np.sin(2 * np.pi * freq * 2 * horn_t) * np.exp(-horn_t * 1.2)
        horn *= np.hanning(length) * 0.15
        out[start:start+length] += horn
    
    # War drums (deep, rhythmic)
    drum_beat = 0.0
    while drum_beat < duration:
        pos = int(drum_beat * SAMPLE_RATE)
        drum_len = min(int(0.3 * SAMPLE_RATE), n - pos - 1)
        if drum_len > 10:
            drum = _lowpass(rng.uniform(-1, 1, drum_len), 100) * np.exp(-np.linspace(0, 10, drum_len)) * 0.2
            out[pos:pos+drum_len] += drum
        drum_beat += rng.uniform(1.5, 3.0)
    
    # Distant shouted commands (muffled voice-band noise)
    cmd_count = max(1, int(duration / 10))
    for _ in range(cmd_count):
        start = rng.integers(0, max(1, n - int(1.5 * SAMPLE_RATE)))
        length = min(int(rng.uniform(0.8, 1.5) * SAMPLE_RATE), n - start)
        voice = _lowpass(_white_noise(length / SAMPLE_RATE, seed=rng.integers(0, 10000)), 
                         rng.integers(30, 80))
        mod = 0.5 + 0.5 * np.sin(2 * np.pi * rng.uniform(0.5, 2.0) * np.linspace(0, length/SAMPLE_RATE, length))
        out[start:start+length] += voice * mod * 0.08
    
    # Horse whinnies (sparse)
    whinny_count = max(1, int(duration / 20))
    for _ in range(whinny_count):
        start = rng.integers(0, max(1, n - int(1.0 * SAMPLE_RATE)))
        length = min(int(rng.uniform(0.5, 1.0) * SAMPLE_RATE), n - start)
        whinny_t = np.linspace(0, length / SAMPLE_RATE, length)
        freq_sweep = np.linspace(rng.uniform(400, 800), rng.uniform(1200, 2000), length)
        whinny = np.sin(2 * np.pi * np.cumsum(freq_sweep) / SAMPLE_RATE) * np.hanning(length) * np.exp(-whinny_t * 2)
        out[start:start+length] += whinny * 0.12
    
    # Metal clanking (sword on shield, armor)
    clang_count = max(1, int(duration / 8))
    for _ in range(clang_count):
        start = rng.integers(0, max(1, n - int(0.5 * SAMPLE_RATE)))
        length = min(int(rng.uniform(0.2, 0.6) * SAMPLE_RATE), n - start)
        clang = _lowpass(rng.uniform(-1, 1, length), 50) * np.exp(-np.linspace(0, 15, length)) ** 2
        out[start:start+length] += clang * 0.06
    
    return np.clip(out + rumble, -1, 1) * 0.35


def _synth_scared_men(duration: float) -> np.ndarray:
    """Quiet breathing, whispered prayers, nervous muttering — not screaming.
    Low, intimate, human. Volume very low."""
    n = max(1, int(duration * SAMPLE_RATE))
    out = np.zeros(n)
    rng = np.random.default_rng(9)
    t = np.linspace(0, duration, n)
    
    # Layer of quiet breaths
    for i in range(6):
        breath = _lowpass(_white_noise(duration, seed=1000 + i), 
                          int(rng.integers(10, 25)))
        mod = 0.4 + 0.6 * np.sin(2 * np.pi * rng.uniform(0.1, 0.3) * t + rng.uniform(0, 6.28))
        out += breath * mod * 0.04
    
    # Whispered prayers/muttering (bandpass in speech range)
    for i in range(4):
        voice = _lowpass(_white_noise(duration, seed=2000 + i), 
                         int(rng.integers(15, 35)))
        mod = 0.3 + 0.7 * np.sin(2 * np.pi * rng.uniform(0.8, 1.8) * t + rng.uniform(0, 6.28))
        out += voice * mod * 0.025
    
    # Occasional sharp intake of breath
    for _ in range(max(1, int(duration / 12))):
        start = rng.integers(0, max(1, n - int(0.5 * SAMPLE_RATE)))
        length = min(int(rng.uniform(0.3, 0.8) * SAMPLE_RATE), n - start)
        gasp = _lowpass(rng.uniform(-1, 1, length), 30) * np.exp(-np.linspace(0, 8, length)) ** 1.5
        out[start:start+length] += gasp * 0.05
    
    return np.clip(out, -1, 1) * 0.25


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
    "air": _synth_air,
    "war_ambience": _synth_war_ambience,
    "scared_men": _synth_scared_men,
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
    (("court", "courtiers", "marketplace", "town square", "gathered crowd", "spectators",
      "onlookers", "murmur", "chatter", "assembly hall"), "crowd"),
    (("forest", "jungle", "wilderness", "nature", "woods"), "birds"),
    (("wind", "gale", "blizzard"), "wind"),
    # War ambience for large-scale battles
    (("army", "battalion", "regiment", "division", "legion", "horde",
      "thousand", "ten thousand", "hundred thousand", "host", "force",
      "siege", "invasion", "assault", "skirmish", "engagement", "front line"),
     "war_ambience"),
    # Scared men for personal danger/desperate scenes
    (("trapped", "surrounded", "ambush", "outnumbered", "last stand", 
      "fear", "terror", "desperate", "hopeless", "doomed", "panic"),
     "scared_men"),
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


def _synth_transition_whoosh(duration: float = 0.6) -> np.ndarray:
    """A quick rising whoosh for scene transitions - sells the cut."""
    n = max(1, int(duration * SAMPLE_RATE))
    t = np.linspace(0, duration, n)
    # Rising pitch + amplitude
    freq = np.linspace(80, 2000, n)
    phase = np.cumsum(2 * np.pi * freq / SAMPLE_RATE)
    sig = np.sin(phase) * np.hanning(n) * t / duration
    # Add breathy noise
    noise = _lowpass(_white_noise(duration), 50) * 0.3
    return np.clip(sig + noise, -1, 1) * 0.4


def _synth_impact_thud(duration: float = 0.4) -> np.ndarray:
    """Low-frequency thud for dramatic beats - like a door slamming."""
    n = max(1, int(duration * SAMPLE_RATE))
    t = np.linspace(0, duration, n)
    # Fundamental thud
    sig = np.sin(2 * np.pi * 60 * t) * np.exp(-t * 15) * 0.6
    # Add harmonic body
    sig += np.sin(2 * np.pi * 120 * t) * np.exp(-t * 10) * 0.3
    # Noise burst
    noise = _lowpass(_white_noise(duration), 20) * np.exp(-t * 20) * 0.2
    return np.clip(sig + noise, -1, 1)


def _synth_magic_shimmer(duration: float = 0.5) -> np.ndarray:
    """High-frequency shimmer for insight/reveal transitions."""
    n = max(1, int(duration * SAMPLE_RATE))
    t = np.linspace(0, duration, n)
    # Multiple bell-like tones
    sig = np.zeros(n)
    for freq in [800, 1200, 1600, 2400]:
        sig += np.sin(2 * np.pi * freq * t) * np.exp(-t * 8) * 0.25
    return np.clip(sig * np.hanning(n), -1, 1)


# Transition SFX mapping by scene role transition
_TRANSITION_SFX = {
    ("hook", "build"): "whoosh",      # hook -> build: quick whoosh
    ("build", "build"): "whoosh",     # build -> build: whoosh
    ("build", "insight"): "shimmer",  # build -> insight: magic shimmer
    ("hook", "insight"): "thud",      # hook -> insight (short video): thud
}


def _get_transition_sfx(prev_role: str, next_role: str) -> Optional[str]:
    return _TRANSITION_SFX.get((prev_role, next_role), "whoosh")


def build_transition_sfx(
    scene_roles: List[str],
    scene_durations: List[float],
    work_dir: Path,
) -> Optional[Path]:
    """Builds a transition SFX track with whooshes/thuds/shimmers at scene boundaries.
    
    Returns a WAV file with transition effects placed at each scene boundary,
    scaled to the transition type (hook->build, build->insight, etc.)."""
    if len(scene_roles) < 2:
        return None
    
    total_duration = sum(scene_durations)
    track = np.zeros(max(1, int(total_duration * SAMPLE_RATE)))
    
    offset = 0.0
    for i in range(len(scene_roles) - 1):
        prev_role = scene_roles[i]
        next_role = scene_roles[i + 1]
        sfx_name = _get_transition_sfx(prev_role, next_role)
        
        if sfx_name == "whoosh":
            sfx = _synth_transition_whoosh(0.6)
        elif sfx_name == "thud":
            sfx = _synth_impact_thud(0.4)
        elif sfx_name == "shimmer":
            sfx = _synth_magic_shimmer(0.5)
        else:
            sfx = _synth_transition_whoosh(0.6)
        
        # Place SFX so it ends exactly at the scene boundary
        start_sample = int((offset + scene_durations[i] - len(sfx) / SAMPLE_RATE) * SAMPLE_RATE)
        end_sample = min(len(track), start_sample + len(sfx))
        if start_sample >= 0 and end_sample > start_sample:
            track[start_sample:end_sample] += sfx[: end_sample - start_sample]
        
        offset += scene_durations[i]
    
    out_path = work_dir / "transitions.wav"
    _write_wav(track, out_path)
    return out_path


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
