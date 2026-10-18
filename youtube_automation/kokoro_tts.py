"""Kokoro-82M narration: free, open (Apache 2.0), runs on CPU - no API key, no billing.

Called from tts.py when voice.provider == "kokoro". tts.synthesize_script falls back
to edge-tts for the WHOLE video if anything here fails, so a bad install or a failed
model download can never break (or mix voices in) a run."""
from __future__ import annotations

import logging
import re
import subprocess
import time
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)

_PIPELINES: dict = {}
_ROLE_SPEED = {"hook": 1.02, "build": 1.0, "insight": 0.93}   # slow the closing insight so it lands
_GAP_SECONDS = 0.18                                            # breath between Kokoro's internal chunks
_SR = 24000


def _rate_multiplier(rate: str) -> float:
    m = re.fullmatch(r"([+-]\d+)%", (rate or "+0%").strip())
    return 1.0 + int(m.group(1)) / 100.0 if m else 1.0


def _get_pipeline(voice_name: str):
    lang = voice_name[:1] or "a"          # kokoro voice ids start with the language: a=US, b=UK
    if lang not in _PIPELINES:
        from kokoro import KPipeline      # lazy: only installed when this provider is used
        _PIPELINES[lang] = KPipeline(lang_code=lang)
    return _PIPELINES[lang]


def _chunk_audio(item):
    import numpy as np
    a = getattr(item, "audio", None)
    if a is None:
        a = item[2]
    if hasattr(a, "detach"):
        a = a.detach().cpu().numpy()
    return np.asarray(a, dtype=np.float32).reshape(-1)


def _chunk_cues(item, text: str, offset: float, dur: float) -> List[Tuple[str, float, float]]:
    """Real per-word timestamps when Kokoro provides them, else spread words by length."""
    toks = getattr(item, "tokens", None) or []
    real = [(t.text, float(t.start_ts) + offset, float(t.end_ts) + offset) for t in toks
            if getattr(t, "start_ts", None) is not None and getattr(t, "end_ts", None) is not None and str(t.text).strip()]
    if real and len(real) >= len(text.split()) * 0.6:
        return real
    words = (getattr(item, "graphemes", None) or text).split()
    total = sum(len(w) + 1 for w in words) or 1
    t, out = offset, []
    for w in words:
        d = dur * (len(w) + 1) / total
        out.append((w, t, t + d))
        t += d
    return out


def synthesize_one(text: str, voice, out_path: Path, role: str = "build") -> List[Tuple[str, float, float]]:
    """Writes an MP3 and returns [(word, start, end), ...] in seconds."""
    import numpy as np
    import soundfile as sf

    started = time.monotonic()
    pipe = _get_pipeline(voice.name)
    speed = _ROLE_SPEED.get(role, 1.0) * _rate_multiplier(voice.rate)
    text = re.sub(r"\s*\|\s*", "... ", text).strip()
    pieces, cues, cursor = [], [], 0.0
    for item in pipe(text, voice=voice.name, speed=speed):
        audio = _chunk_audio(item)
        if audio.size == 0:
            continue
        dur = audio.size / _SR
        chunk_text = getattr(item, "graphemes", None) or text
        cues += _chunk_cues(item, chunk_text, cursor, dur)
        pieces += [audio, np.zeros(int(_GAP_SECONDS * _SR), np.float32)]
        cursor += dur + _GAP_SECONDS
    if not pieces:
        raise RuntimeError("Kokoro returned no audio")
    wav = Path(out_path).with_suffix(".kokoro.wav")
    sf.write(str(wav), np.concatenate(pieces), _SR)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-ar", "44100", "-b:a", "192k", str(out_path)], check=True)
    wav.unlink(missing_ok=True)
    took = time.monotonic() - started
    logger.info("kokoro: %.1fs audio in %.1fs (%.2fx real-time)", cursor, took, cursor / max(took, 0.01))
    return cues
