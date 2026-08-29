"""Multi-language dubbing: translate transcript and re-voice with Piper TTS."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None

try:
    from piper import PiperVoice
except ImportError:
    PiperVoice = None

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from clipai_config import app_config as config
except ImportError:
    class _Config:
        PIPER_VOICES_DIR = os.environ.get("PIPER_VOICES_DIR", "./voices")
    config = _Config()

try:
    import pipeline_lib
except ImportError:
    pipeline_lib = None

logger = logging.getLogger("clipai.dub")

BASE_DIR = Path(__file__).parent
VOICES_DIR = os.environ.get("PIPER_VOICES_DIR", os.path.join(BASE_DIR, "voices"))

DUB_LANGUAGES = {
    "es": {"label": "Spanish", "voice": "es_ES-carlfm-x_low"},
    "fr": {"label": "French", "voice": "fr_FR-siwis-low"},
    "pt": {"label": "Portuguese", "voice": "pt_BR-faber-medium"},
}

_voice_cache: dict = {}


def get_voice(lang_code: str):
    if lang_code not in _voice_cache:
        if not PiperVoice:
            raise RuntimeError("piper-tts not installed")
        model_path = os.path.join(VOICES_DIR, f"{DUB_LANGUAGES[lang_code]['voice']}.onnx")
        _voice_cache[lang_code] = PiperVoice.load(model_path)
    return _voice_cache[lang_code]


def translate_text(text: str, target_lang: str, source_lang: str = "en") -> str:
    if not GoogleTranslator:
        raise RuntimeError("deep-translator not installed")
    return GoogleTranslator(source=source_lang, target=target_lang).translate(text)


def synthesize_speech(text: str, target_lang: str, out_wav_path: str):
    voice = get_voice(target_lang)
    import wave
    with wave.open(out_wav_path, "wb") as wav_file:
        voice.synthesize_wav(text, wav_file)


def _wav_duration(path: str) -> float:
    import wave
    with wave.open(path, "rb") as f:
        return f.getnframes() / float(f.getframerate())


def _atempo_chain(factor: float) -> str:
    factor = max(0.2, min(5.0, factor))
    filters = []
    remaining = factor
    while remaining < 0.5 or remaining > 2.0:
        step = 2.0 if remaining > 2.0 else 0.5
        filters.append(f"atempo={step}")
        remaining /= step
    filters.append(f"atempo={remaining:.4f}")
    return ",".join(filters)


def render_dubbed_clip(
    video_path: str,
    seg: dict,
    out_dir: str,
    rank: int,
    target_lang: str,
    source_lang: str = "en",
    watermark: bool = True,
) -> tuple[str, str, bool, str]:
    """Render a clip with dubbed audio and translated captions."""
    if not GoogleTranslator or not PiperVoice:
        raise RuntimeError("Dubbing requires deep-translator and piper-tts")

    translated = translate_text(seg["text"], target_lang, source_lang)
    virality = seg.get("virality_score", 0)

    raw_wav = os.path.join(out_dir, f"peakcut_rank{rank}_v{virality}_dub_raw.wav")
    synthesize_speech(translated, target_lang, raw_wav)

    clip_duration = max(0.1, seg["end"] - seg["start"])
    tts_duration = _wav_duration(raw_wav)
    tempo_filter = _atempo_chain(tts_duration / clip_duration)

    stretched_wav = os.path.join(out_dir, f"peakcut_rank{rank}_v{virality}_dub.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", raw_wav, "-af", tempo_filter, stretched_wav],
        capture_output=True, text=True,
    )
    os.unlink(raw_wav)

    # Build SRT from translated text (approximate word timing)
    srt_path = os.path.join(out_dir, f"peakcut_rank{rank}_v{virality}.srt")
    words = translated.split()
    chunk_size = 3
    lines, idx = [], 1
    n_chunks = max(1, (len(words) + chunk_size - 1) // chunk_size)
    for i in range(0, len(words), chunk_size):
        chunk = words[i:i + chunk_size]
        chunk_idx = i // chunk_size
        start = clip_duration * chunk_idx / n_chunks
        end = clip_duration * (chunk_idx + 1) / n_chunks
        if pipeline_lib:
            srt_ts = pipeline_lib.srt_timestamp
        else:
            def srt_ts(t):
                ms = int(round(t * 1000))
                h, ms = divmod(ms, 3600000)
                m, ms = divmod(ms, 60000)
                s, ms = divmod(ms, 1000)
                return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
        lines.append(f"{idx}\n{srt_ts(start)} --> {srt_ts(end)}\n{' '.join(chunk)}\n")
        idx += 1
    with open(srt_path, "w") as f:
        f.write("\n".join(lines))

    out_path = os.path.join(out_dir, f"peakcut_rank{rank}_v{virality}.mp4")
    vf = (
        "scale=1080:-2,pad=1080:1920:0:(1920-ih)/2:color=0x1a1a2e,"
        f"subtitles={srt_path}:force_style='FontName=DejaVu Sans,FontSize=30,"
        "PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BorderStyle=1,Outline=3,"
        "Bold=1,Alignment=2,MarginV=140'"
    )
    if watermark:
        vf += (
            f",drawtext=text='{pipeline_lib.WATERMARK if pipeline_lib else 'FREE PLAN — Peakcut'}'"
            ":fontcolor=white@0.6:fontsize=18:x=(w-text_w)/2:y=h-70"
        )
    cmd = [
        "ffmpeg", "-y", "-ss", str(seg["start"]), "-to", str(seg["end"]),
        "-i", video_path, "-i", stretched_wav,
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", vf, "-shortest",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    os.unlink(stretched_wav)
    return out_path, translated, result.returncode == 0, result.stderr[-800:]