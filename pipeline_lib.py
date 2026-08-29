"""Video processing pipeline: transcribe, score, pick clips, render with captions."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional

from faster_whisper import WhisperModel

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from clipai_config import app_config as config, WHISPER_MODEL as CFG_WHISPER_MODEL
except ImportError:
    import os
    class _Config:
        WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "tiny")
        PIPER_VOICES_DIR = os.environ.get("PIPER_VOICES_DIR", "./voices")
    config = _Config()
    CFG_WHISPER_MODEL = config.WHISPER_MODEL

logger = logging.getLogger("clipai.pipeline")

# ─── Constants ──────────────────────────────────────────────────────────────
WATERMARK = "FREE PLAN — Peakcut"
WHISPER_MODEL = CFG_WHISPER_MODEL

_model = None


def get_model():
    global _model
    if _model is None:
        _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _model


def unload_model():
    global _model
    import gc
    _model = None
    gc.collect()


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: List[Dict]


# ─── Transcription ──────────────────────────────────────────────────────────

def transcribe(video_path: str) -> tuple[List[Segment], float, str]:
    """Transcribe video with word-level timestamps."""
    model = get_model()
    segments, info = model.transcribe(video_path, word_timestamps=True)
    out = []
    for seg in segments:
        words = [{"word": w.word.strip(), "start": w.start, "end": w.end} for w in (seg.words or [])]
        out.append(Segment(start=seg.start, end=seg.end, text=seg.text.strip(), words=words))
    return out, info.duration, info.language


# ─── Audio Energy Scoring ───────────────────────────────────────────────────

def audio_energy_db(video_path: str, start: float, end: float) -> float:
    duration = max(0.1, end - start)
    cmd = [
        "ffmpeg", "-hide_banner", "-ss", str(start), "-t", str(duration),
        "-i", video_path, "-af", "astats=metadata=1:reset=1", "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    matches = re.findall(r"RMS level dB:\s*(-?\d+\.?\d*)", result.stderr)
    vals = [float(m) for m in matches if m != "-inf"]
    return sum(vals) / len(vals) if vals else -60.0


# ─── Text Signal Scoring ────────────────────────────────────────────────────

def text_signal_score(text: str) -> float:
    score = 0.0
    score += text.count("!") * 2.0
    score += text.count("?") * 1.0
    contrast_words = ["but", "yet", "however", "so", "because"]
    score += sum(text.lower().count(w) for w in contrast_words) * 1.5
    words = text.split()
    if words:
        avg_word_len = sum(len(w) for w in words) / len(words)
        score += max(0, 6 - avg_word_len)
    score += min(len(words), 20) * 0.1
    return score


def virality_score(composite: float) -> int:
    return int(min(99, max(35, round(composite * 4 + 15))))


def score_candidates(video_path: str, segments: List[Segment], min_dur=3.0, max_dur=16.0) -> List[Dict]:
    scored = []
    for seg in segments:
        dur = seg.end - seg.start
        if dur < min_dur or dur > max_dur:
            continue
        energy = audio_energy_db(video_path, seg.start, seg.end)
        energy_score = max(0.0, (energy + 40) / 4)
        text_score = text_signal_score(seg.text)
        composite = energy_score + text_score
        scored.append({
            **seg.__dict__, "energy_db": round(energy, 2), "composite": round(composite, 2),
            "virality_score": virality_score(composite),
        })
    scored.sort(key=lambda r: r["composite"], reverse=True)
    return scored


def pick_top_n(scored: List[Dict], n=3, min_gap=2.0) -> List[Dict]:
    picked = []
    for cand in scored:
        overlaps = any(
            not (cand["end"] < p["start"] - min_gap or cand["start"] > p["end"] + min_gap)
            for p in picked
        )
        if not overlaps:
            picked.append(cand)
        if len(picked) >= n:
            break
    return picked


# ─── Caption Rendering ──────────────────────────────────────────────────────

FILLER_WORDS = {"um", "uh", "uhh", "umm", "erm", "ah", "hm", "hmm"}


def _is_filler(word_text: str) -> bool:
    return re.sub(r"[^a-z]", "", word_text.lower()) in FILLER_WORDS


def srt_timestamp(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_word_chunk_srt(words: List[Dict], clip_start: float, chunk_size=4, clean_fillers=True) -> str:
    if clean_fillers:
        words = [w for w in words if not _is_filler(w["word"])]
    lines = []
    idx = 1
    for i in range(0, len(words), chunk_size):
        chunk = words[i:i + chunk_size]
        if not chunk:
            continue
        start = chunk[0]["start"] - clip_start
        end = chunk[-1]["end"] - clip_start
        if end <= start:
            end = start + 0.4
        text = " ".join(w["word"] for w in chunk)
        lines.append(f"{idx}\n{srt_timestamp(max(0, start))} --> {srt_timestamp(end)}\n{text}\n")
        idx += 1
    return "\n".join(lines)


def render_clip(
    video_path: str,
    seg: Dict,
    out_dir: str,
    rank: int,
    watermark: bool = True,
    clip_format: str = "vertical",
    caption_style: str = "bold",
) -> tuple[str, bool, str]:
    srt_text = build_word_chunk_srt(seg["words"], seg["start"])
    virality = seg.get("virality_score", 0)
    srt_path = os.path.join(out_dir, f"peakcut_rank{rank}_v{virality}.srt")
    with open(srt_path, "w") as f:
        f.write(srt_text)

    out_path = os.path.join(out_dir, f"peakcut_rank{rank}_v{virality}_{clip_format}.mp4")

    if clip_format == "square":
        scale_pad = "scale=1080:-2,pad=1080:1080:(1080-w)/2:(1080-h)/2:color=0x1a1a2e"
    elif clip_format == "horizontal":
        scale_pad = "scale=1920:-2,pad=1920:1080:(1920-w)/2:(1080-h)/2:color=0x1a1a2e"
    else:  # vertical
        scale_pad = "scale=1080:-2,pad=1080:1920:0:(1920-ih)/2:color=0x1a1a2e"

    caption_styles = {
        "bold": "FontName=DejaVu Sans,FontSize=30,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BorderStyle=1,Outline=3,Bold=1,Alignment=2,MarginV=140",
        "outline": "FontName=DejaVu Sans,FontSize=30,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BorderStyle=1,Outline=4,Bold=0,Alignment=2,MarginV=140",
        "subtle": "FontName=DejaVu Sans,FontSize=28,PrimaryColour=&HB8B8B8,OutlineColour=&H000000,BorderStyle=1,Outline=1,Bold=0,Alignment=2,MarginV=140",
        "neon": "FontName=DejaVu Sans,FontSize=32,PrimaryColour=&H00FFFF,OutlineColour=&H000000,BorderStyle=1,Outline=2,Bold=1,Alignment=2,MarginV=140,BackColour=&H00000080",
    }
    caption_style_str = caption_styles.get(caption_style, caption_styles["bold"])

    vf = f"{scale_pad},subtitles={srt_path}:force_style='{caption_style_str}'"
    if watermark:
        vf += f",drawtext=text='{WATERMARK}':fontcolor=white@0.6:fontsize=18:x=(w-text_w)/2:y=h-70"

    cmd = [
        "ffmpeg", "-y", "-ss", str(seg["start"]), "-to", str(seg["end"]),
        "-i", video_path, "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return out_path, result.returncode == 0, result.stderr[-800:]


# ─── Main Pipeline ──────────────────────────────────────────────────────────

def process_video(
    video_path: str,
    out_dir: str,
    n_clips: int = 3,
    watermark: bool = True,
    dub_lang: Optional[str] = None,
    clip_format: str = "vertical",
    caption_style: str = "bold",
) -> Dict:
    os.makedirs(out_dir, exist_ok=True)
    segments, duration, source_lang = transcribe(video_path)

    if dub_lang and source_lang != "en":
        raise ValueError(f"Dubbing only supports English source (detected: {source_lang})")

    if dub_lang:
        unload_model()

    scored = score_candidates(video_path, segments)
    top = pick_top_n(scored, n=n_clips)

    manifest = []
    for i, seg in enumerate(top, 1):
        if dub_lang:
            import dub_lib
            out_path, translated_text, ok, err = dub_lib.render_dubbed_clip(
                video_path, seg, out_dir, i, dub_lang, source_lang, watermark
            )
            text = translated_text
        else:
            out_path, ok, err = render_clip(
                video_path, seg, out_dir, i, watermark, clip_format, caption_style
            )
            text = seg["text"]
        manifest.append({
            "rank": i, "start": seg["start"], "end": seg["end"],
            "score": seg["composite"], "virality_score": seg["virality_score"],
            "text": text, "file": os.path.basename(out_path), "ok": ok,
            "error": None if ok else err,
        })

    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    return {"duration": duration, "clips": manifest, "language": source_lang}