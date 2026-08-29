"""Text-to-speech narration - Microsoft Edge's free neural voices (edge-tts)
by default, or Google Cloud TTS's Neural2 voices (see google_tts.py) when
config.voice.provider == "google" and GOOGLE_TTS_API_KEY is set.

Each scene is synthesized to its own audio file so the assembler knows exactly
how long to hold that scene's visuals for, and word-boundary timestamps are
kept so subtitles.py can burn in captions that track the voiceover.

EXPRESSIVENESS FEATURES:
- SSML support for prosody control (rate, pitch, volume, breaks)
- Emphasis markup: **word** or <emphasis>word</emphasis> -> SSML emphasis
- Breathing pauses: | or <break time="500ms"/> inserted at commas/periods
- Scene-role-aware defaults: hook=urgent (faster, higher pitch), insight=contemplative (slower, lower)
- Per-word timing preserved for subtitle sync
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import List, Optional, Tuple

import edge_tts

from . import google_tts
from .config import VoiceConfig
from .script_writer import Script

logger = logging.getLogger(__name__)

# edge-tts's free endpoint occasionally drops a request with NoAudioReceived
# for no discernible reason (no malformed input involved) - worth a few
# retries rather than failing a whole scheduled run over it, same rationale
# as the Gemini retry logic in script_writer.py.
_MAX_TTS_RETRIES = 3

# Used when voice.provider == "google" but GOOGLE_TTS_API_KEY isn't set yet -
# config.yaml's voice.name is then a Google-only voice id (e.g. "en-US-Neural2-D"),
# which edge-tts rejects outright, so the fallback needs its own known-good
# edge-tts voice rather than reusing voice.name verbatim.
_EDGE_TTS_FALLBACK_VOICE = "en-US-AvaMultilingualNeural"

# Emphasis/breathing-pause markup gets stripped down to plain text (see
# _apply_expressiveness) rather than converted to SSML - edge_tts.Communicate
# has no supported way to receive embedded per-word SSML tags; see that
# function's docstring for how this was confirmed.
_EMPHASIS_STRIP_PATTERNS = [
    (r"\*\*(.+?)\*\*", r"\1"),                     # **word** -> word
    (r"<emphasis[^>]*>(.+?)</emphasis>", r"\1"),   # strip any stray <emphasis> tags down to their text
]

_BREATH_STRIP_PATTERNS = [
    (r",\s*\|", ","),    # ,| -> , (natural pause already there)
    (r"\.\s*\|", "."),   # .| -> .
    (r"\|\s*", "... "),  # standalone pipe -> an ellipsis, which edge-tts's own sentence pacing actually honors
]

# Scene-role prosody deltas, layered on top of the voice's own base
# rate/pitch (see _prosody_kwargs) via edge_tts.Communicate's real
# constructor kwargs - NOT embedded SSML (edge_tts doesn't support that; see
# _apply_expressiveness). Units are strict and validated by edge_tts itself
# (edge_tts.data_classes.TTSConfig): rate/volume as integer percent
# ("+N%"), pitch as integer Hz ("+NHz") - NOT semitones/dB, which the
# previous version of this table used and which would have raised
# ValueError from edge_tts's own validation had they ever actually reached
# the Communicate constructor (they hadn't - see _apply_expressiveness).
_ROLE_PROSODY = {
    "hook":     {"rate": "+15%", "pitch": "+20Hz", "volume": "+10%"},   # urgent, engaging
    "build":    {"rate": "+5%",  "pitch": "+8Hz",  "volume": "+0%"},    # steady
    "insight":  {"rate": "-10%", "pitch": "-12Hz", "volume": "-10%"},   # contemplative, authoritative
}


@dataclass
class WordCue:
    text: str
    start: float  # seconds, relative to this scene's audio
    end: float


@dataclass
class SceneAudio:
    scene_index: int
    audio_path: Path
    duration: float
    cues: List[WordCue]


def _approx_cues_from_text(text: str, audio_path: Path) -> List[WordCue]:
    """Create approximate word cues when TTS doesn't return word boundaries.
    Distributes words evenly across the audio duration."""
    try:
        duration = _probe_duration(audio_path)
    except Exception:
        duration = max(1.0, len(text.split()) * 0.4)  # fallback estimate
    
    words = text.split()
    if not words:
        return []
    
    cues: List[WordCue] = []
    word_duration = duration / len(words)
    t = 0.0
    for w in words:
        cues.append(WordCue(text=w, start=t, end=t + word_duration))
        t += word_duration
    return cues


def _apply_expressiveness(text: str) -> str:
    """Strips emphasis (`**bold**`) and breathing-pause (`|`) markup down to
    plain, TTS-safe text.

    This used to wrap the (still-markup-laden) text in hand-built SSML
    (<speak><prosody>...<emphasis>...<break/>...</prosody></speak>) and hand
    that whole string to edge_tts.Communicate() as its `text` argument. But
    Communicate() escapes and wraps *whatever text it's given* into its own
    SSML internally (see edge_tts.communicate.Communicate.__init__ ->
    mkssml(escape(text))) - it has no code path that parses SSML tags out of
    the string you pass it. Confirmed directly: escape() turns our own
    "<speak version=...>" into the literal characters "&lt;speak
    version=...", so the voice ended up speaking that raw markup out loud as
    words, prepended/appended to every scene's real narration - a silent
    bug, since Communicate() doesn't error on this, it just "succeeds" with
    wrong audio. edge-tts has no supported way to send inline per-word SSML
    (emphasis/breaks) through Communicate - only whole-utterance rate/pitch/
    volume are real, via constructor kwargs (see _prosody_kwargs). So this
    now only strips the markup down to something safe to actually speak,
    rather than trying to preserve emphasis/pauses this library can't
    express."""
    for pattern, repl in _EMPHASIS_STRIP_PATTERNS:
        text = re.sub(pattern, repl, text)
    for pattern, repl in _BREATH_STRIP_PATTERNS:
        text = re.sub(pattern, repl, text)
    return text


def _combine_percent(base: str, delta: str) -> str:
    total = int(base.rstrip("%")) + int(delta.rstrip("%"))
    return f"{total:+d}%"


def _combine_hz(base: str, delta: str) -> str:
    total = int(base.rstrip("Hz")) + int(delta.rstrip("Hz"))
    return f"{total:+d}Hz"


def _prosody_kwargs(role: str, base_rate: str = "+0%", base_pitch: str = "+0Hz") -> dict:
    """Real rate/pitch/volume kwargs for edge_tts.Communicate's constructor -
    the only place these settings actually take effect (see
    _apply_expressiveness for why embedding them in the text does not).
    Layers the scene role's prosody delta on top of the voice's own base
    rate/pitch (config.yaml's voice.rate/voice.pitch, "+0%"/"+0Hz" by
    default) rather than discarding it, so a channel-level voice-speed
    tweak still applies underneath the per-role variation. edge_tts itself
    strictly validates these formats (integer percent for rate/volume,
    integer Hz for pitch - see edge_tts.data_classes.TTSConfig), which is
    also why the results are formatted via _combine_percent/_combine_hz
    rather than simple string concatenation."""
    prosody = _ROLE_PROSODY.get(role, _ROLE_PROSODY["build"])
    return {
        "rate": _combine_percent(base_rate, prosody["rate"]),
        "pitch": _combine_hz(base_pitch, prosody["pitch"]),
        "volume": prosody["volume"],
    }


async def _synthesize_one(text: str, voice: VoiceConfig, out_path: Path, role: str = "build") -> List[WordCue]:
    clean_text = _apply_expressiveness(text)
    prosody = _prosody_kwargs(role, base_rate=voice.rate, base_pitch=voice.pitch)

    try:
        communicate = edge_tts.Communicate(
            clean_text, voice.name,
            rate=prosody["rate"], pitch=prosody["pitch"], volume=prosody["volume"],
            boundary="WordBoundary",
        )
        cues: List[WordCue] = []
        with open(out_path, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / 10_000_000  # 100-ns units -> seconds
                    cues.append(
                        WordCue(
                            text=chunk["text"],
                            start=start,
                            end=start + chunk["duration"] / 10_000_000,
                        )
                    )
        if cues:
            return cues
        # If no cues but audio generated, create approximate cues from text
        logger.warning(f"TTS generated audio but no word boundaries for scene role={role}; creating approximate cues")
        return _approx_cues_from_text(text, out_path)
    except edge_tts.exceptions.NoAudioReceived as exc:
        raise RuntimeError(f"edge-tts returned no audio: {exc}") from exc


def _synthesize_one_with_retry(text: str, voice: VoiceConfig, out_path: Path, role: str = "build") -> List[WordCue]:
    last_error = None
    for attempt in range(_MAX_TTS_RETRIES + 1):
        try:
            return asyncio.run(_synthesize_one(text, voice, out_path, role))
        except edge_tts.exceptions.NoAudioReceived as exc:
            last_error = exc
            if attempt < _MAX_TTS_RETRIES:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(
                f"edge-tts returned no audio after {_MAX_TTS_RETRIES + 1} attempts: {last_error}"
            ) from exc
    raise AssertionError("unreachable")  # loop always returns or raises


def _synthesize_one_google_with_retry(text: str, voice: VoiceConfig, api_key: str, out_path: Path) -> List[WordCue]:
    cues = google_tts.synthesize_one(text, voice, api_key, out_path)
    return [WordCue(text=word, start=start, end=end) for word, start, end in cues]


def _resolve_synthesizer(voice: VoiceConfig, google_api_key: Optional[str]):
    """Picks which provider actually synthesizes each scene. Falls back to
    edge-tts (never hard-fails a run) if voice.provider == "google" but no
    key is configured yet - see config.py's Secrets.google_tts_api_key."""
    if voice.provider == "google":
        if google_api_key:
            return lambda text, out_path, role="build": _synthesize_one_google_with_retry(text, voice, google_api_key, out_path)
        logger.warning(
            "voice.provider is 'google' but GOOGLE_TTS_API_KEY is not set - falling back to edge-tts for this run."
        )
        voice = replace(voice, name=_EDGE_TTS_FALLBACK_VOICE)
    return lambda text, out_path, role="build": _synthesize_one_with_retry(text, voice, out_path, role)


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def concat_audio(paths: List[Path], out_path: Path) -> Path:
    """Decode-and-reconcatenate (rather than stream-copy concat) so per-file mp3
    encoder padding doesn't accumulate into audible drift across segments."""
    inputs = []
    for p in paths:
        inputs += ["-i", str(p)]
    filter_inputs = "".join(f"[{i}:a]" for i in range(len(paths)))
    filter_complex = f"{filter_inputs}concat=n={len(paths)}:v=0:a=1[out]"
    subprocess.run(
        [
            "ffmpeg", "-y", *inputs,
            "-filter_complex", filter_complex, "-map", "[out]",
            str(out_path),
        ],
        check=True, capture_output=True,
    )
    return out_path


def synthesize_script(
    script: Script, voice: VoiceConfig, work_dir: Path, google_api_key: Optional[str] = None,
) -> Tuple[List[SceneAudio], Path]:
    """Synthesize every scene's narration, returning per-scene audio and a
    single concatenated narration track for the final mix."""
    work_dir.mkdir(parents=True, exist_ok=True)
    scenes: List[SceneAudio] = []
    synthesize_one = _resolve_synthesizer(voice, google_api_key)

    for i, scene in enumerate(script.scenes):
        out_path = work_dir / f"scene_{i:02d}.mp3"
        cues = synthesize_one(scene.narration, out_path, scene.role)
        duration = _probe_duration(out_path)
        scenes.append(SceneAudio(scene_index=i, audio_path=out_path, duration=duration, cues=cues))

    full_narration = concat_audio([s.audio_path for s in scenes], work_dir / "narration_full.mp3")
    return scenes, full_narration


def silent_audio(duration: float, out_path: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "anullsrc=channel_layout=mono:sample_rate=24000",
            "-t", f"{duration:.3f}", str(out_path),
        ],
        check=True, capture_output=True,
    )
    return out_path
