"""Text-to-speech via Google Cloud's Text-to-Speech REST API (Neural2 voices).

An alternative to edge-tts (see tts.py) for better narration quality -
Neural2 voices get 1M characters/month free, comfortably covering daily
longform narration (a longform script is roughly 15-25K characters, so
~30 videos/month stays well inside the free tier). Selected via
config.voice.provider == "google"; tts.py falls back to edge-tts
automatically if GOOGLE_TTS_API_KEY isn't set, so this is opt-in, not a
hard requirement.

Google's REST API has no built-in word-boundary stream like edge-tts's
WordBoundary chunks. Instead, an SSML <mark/> tag is inserted before every
word and enableTimePointing is requested; the response returns each mark's
timeSeconds, and a word's end time is approximated as the next word's start
(or the clip's total duration for the last word).
"""
from __future__ import annotations

import base64
import json
import subprocess
import time
from pathlib import Path
from typing import List, Tuple

import requests

from .config import VoiceConfig

API_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"

# Same rationale as script_writer.py/tts.py's other retry logic - transient
# 429/503s are common on shared free-tier API endpoints and worth retrying
# rather than failing a whole scheduled run over one flaky request.
_RETRY_STATUSES = {429, 503}
_MAX_RETRIES = 4


def _escape_ssml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _build_ssml(text: str, words: List[str]) -> str:
    marked = [f'<mark name="w{i}"/>{_escape_ssml(word)}' for i, word in enumerate(words)]
    return "<speak>" + " ".join(marked) + "</speak>"


def _language_code(voice_name: str) -> str:
    """Google voice names are "<lang>-<REGION>-<...>", e.g.
    "en-US-Neural2-D" -> "en-US". A trailing rsplit("-", 1) grabs the wrong
    two segments here (e.g. "en-US-Neural2"), which isn't a valid BCP-47
    language code, so this takes the first two segments explicitly."""
    parts = voice_name.split("-")
    return "-".join(parts[:2]) if len(parts) >= 2 else "en-US"


def _parse_rate(rate: str) -> float:
    """edge-tts style "+10%"/"-15%"/"+0%" -> Google's speakingRate multiplier
    (0.25-4.0, 1.0 = normal)."""
    try:
        pct = float(rate.strip().replace("%", ""))
    except ValueError:
        return 1.0
    return max(0.25, min(4.0, 1.0 + pct / 100))


def _parse_pitch(pitch: str) -> float:
    """edge-tts style "+0Hz" has no exact Google equivalent (Google's pitch
    is in semitones, not Hz) - "+0Hz" (no adjustment, the config default)
    maps cleanly to 0; anything else is a rough best-effort scale, not a
    precise conversion."""
    stripped = pitch.strip().replace("Hz", "")
    try:
        value = float(stripped)
    except ValueError:
        return 0.0
    return 0.0 if value == 0 else max(-20.0, min(20.0, value / 5))


def synthesize_one(text: str, voice: VoiceConfig, api_key: str, out_path: Path) -> List[Tuple[str, float, float]]:
    """Synthesizes text to out_path (MP3) and returns [(word, start, end), ...]
    in seconds, relative to the start of this clip. Raises RuntimeError on a
    persistent API failure after retries."""
    words = text.split()
    body = {
        "input": {"ssml": _build_ssml(text, words)},
        "voice": {"languageCode": _language_code(voice.name), "name": voice.name},
        "audioConfig": {
            "audioEncoding": "MP3",
            "speakingRate": _parse_rate(voice.rate),
            "pitch": _parse_pitch(voice.pitch),
        },
        "enableTimePointing": ["SSML_MARK"],
    }

    last_error = None
    response = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = requests.post(API_URL, params={"key": api_key}, json=body, timeout=60)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            last_error = str(exc)
            if attempt < _MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Google TTS request timed out after {_MAX_RETRIES + 1} attempts: {last_error}") from exc

        if response.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
            last_error = response.text
            time.sleep(2 ** attempt)
            continue
        break

    if response.status_code != 200:
        raise RuntimeError(f"Google TTS API error {response.status_code}: {response.text[:2000]}")

    data = response.json()
    audio_bytes = base64.b64decode(data["audioContent"])
    out_path.write_bytes(audio_bytes)

    timepoints = {tp["markName"]: tp["timeSeconds"] for tp in data.get("timepoints", [])}
    starts = [timepoints.get(f"w{i}", 0.0) for i in range(len(words))]
    clip_duration = _probe_duration(out_path)

    cues = []
    for i, word in enumerate(words):
        start = starts[i]
        end = starts[i + 1] if i + 1 < len(starts) else max(start + 0.1, clip_duration)
        cues.append((word, start, end))
    return cues


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])
