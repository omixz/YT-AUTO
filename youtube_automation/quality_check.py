"""Cheap heuristic gates that run before upload.

Two phases, since the things worth checking exist at different points in
the pipeline:

- `check()` runs right after the script is written - too few words, too few
  scenes, or missing the hook/insight structure the script prompt was told
  to follow. This is exactly what YouTube's reused/duplicative content
  policy targets, so catching it matters even before anything is rendered.
  It also enforces the one deliberate exception to the "only catch breakage,
  not writing quality" rule below: the title must use one of a handful of
  genuinely-interesting hook shapes (cause-and-effect, immersive daily-life
  curiosity, myth/legend, hidden-truth reveal) rather than a vague listicle
  or topic label - see require_strong_hook.
- `check_media()` runs after the final video is assembled - it actually
  inspects the rendered file (via ffprobe) rather than trusting that every
  upstream step worked, catching the class of bug where a renderer or mixer
  step silently produces something broken: a truncated render, a video with
  no audio track, a mix so quiet it reads as silent, wrong resolution, or
  captions that never actually got word-cue data.

A failing gate (either phase) still gets built and uploaded (never silently
dropped) - it's just uploaded under quality.fallback_privacy_status instead
of the configured public/unlisted default, so a weak or broken episode
doesn't go out unattended and a human can decide by hand.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import List, Tuple

from .config import PipelineConfig
from .script_writer import Script
from .tts import SceneAudio

logger = logging.getLogger(__name__)

# Below this mean_volume (dBFS, from ffmpeg's volumedetect), a mix reads as
# effectively silent or broken rather than just "quiet content" - the
# louder mix landed on earlier this session runs narration alone at roughly
# -13 to -18dB mean, so anything this far under it means a layer (or all of
# them) didn't make it into the final mux.
MIN_MEAN_VOLUME_DB = -40.0

# How far the rendered video's duration is allowed to drift from the sum of
# its scene audio durations before it's flagged as a truncated/corrupted
# render rather than just normal encoder rounding.
MAX_DURATION_DRIFT_FRACTION = 0.10
MAX_DURATION_DRIFT_SECONDS = 5.0


# The checks below all target genuine generation failures - a refused/hedged
# response, truncated output, leftover formatting artifacts, byte-identical
# repeated scenes - not subjective judgments about whether the writing is
# good. That distinction matters: a heuristic that scored *quality* would
# inevitably misfire on some fraction of genuinely good scripts, which is
# exactly the false-positive risk to avoid here. These only fire on things
# that are unambiguously broken regardless of how good the topic/writing is.

_REFUSAL_PATTERNS = (
    "i cannot", "i can't", "i'm sorry, but", "i am sorry, but",
    "as an ai", "as a language model", "i am unable to", "i'm unable to",
)

_MARKDOWN_ARTIFACTS = ("**", "##", "```", "](http")

_PLACEHOLDER_PATTERNS = ("[insert", "[todo", "todo:", "lorem ipsum", "<placeholder>", "xxxxx")

# The script prompt explicitly forbids these ("no scene-setting, no 'today
# we're looking at...' throat-clearing") - the hook's first sentence is
# supposed to deliver the title's promise immediately, so an opener like
# this is a direct violation of an instruction the prompt already gives,
# not a stylistic guess.
_WEAK_HOOK_OPENERS = (
    "today we're", "today, we're", "in this video", "welcome back",
    "let's talk about", "let's dive into",
)

MIN_SCENE_WORDS = 3
MIN_DESCRIPTION_WORDS = 8
MIN_TAGS = 3

# The "10/10, super interesting" bar: the title must use a genuinely
# interesting hook shape, not a vague listicle ("5 Facts About Rome") or
# bare topic label ("Ancient Rome: A Documentary"). This isn't limited to
# cause-and-effect - "how did the death of X cause Y" was the first version
# of this gate, but that excluded exactly the content that performs well:
# immersive daily-life stories, mythology retellings, hidden-truth reveals.
# Each marker group below is a cheap, low-collision signal for one of the
# hook shapes the script prompt asks for; the title only needs to match one.
#
# A "has a named entity" check was also considered (checking for a
# capitalized word) but real titles come back in Title Case ("How A Small
# Mistake Caused A Huge Disaster"), which capitalizes every word regardless
# of whether any of them name something specific - that check would have
# given false confidence rather than real detection, so it was dropped.
_STRONG_HOOK_MARKERS = (
    # cause -> consequence (a trigger that set something off)
    "caus", "trigger", "spark", "led to", "leads to", "lead to",
    "start", "set off", "unleash", "result in", "resulted in", "chang",
    # regression: "How a Politician's Single Typo Accidentally Destroyed the
    # Berlin Wall" is a textbook cause->consequence hook but used none of the
    # above connectors - real production title, rejected before this was added.
    "accidentally", "by accident", "by mistake", "single typo", "one typo",
    "single mistake", "one mistake",
    # averted disaster: just as causally significant as triggering one, but
    # inverted polarity ("prevented/stopped/saved" instead of "caused") -
    # missing this class of connector is what let a genuinely great title
    # ("How One Stubborn Soviet Submarine Officer Single-Handedly Saved the
    # World") get rejected in real production; this whole group was added
    # in direct response to that.
    "saved the world", "single-handedly", "prevented", "averted", "stopped",
    "foiled", "thwarted", "narrowly avoided", "nearly caused", "almost started",
    "stood between", "on the brink of",
    # immersive daily-life curiosity
    "what was it really like", "what it was really like", "what life was really like",
    "really like to be", "really like to live", "daily life",
    # myth/legend (excluding "myth" itself - see _MYTH_WORD_RE below)
    "legend", "the god ", "the goddess ",
    # hidden-truth reveal
    "the secret", "the truth about", "what really happened", "the untold",
    "didn't want", "never told", "hidden truth",
)

# "myth" needs its own word-boundary check rather than a plain substring
# match: "myth" is literally a substring of "mythology" (as in "Greek
# Mythology Explained", the exact bare topic-label title this gate exists
# to reject), so a naive `"myth" in title` let precisely the wrong titles
# through. Found this via testing before shipping, not in production.
_MYTH_WORD_RE = re.compile(r"\bmyths?\b")


def _has_strong_hook_marker(text: str) -> bool:
    lower = f" {text.lower()} "
    if _MYTH_WORD_RE.search(lower):
        return True
    return any(m in lower for m in _STRONG_HOOK_MARKERS)


def check(script: Script, config: PipelineConfig) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    q = config.quality

    word_count = len(script.full_narration.split())
    if word_count < q.min_words:
        reasons.append(f"only {word_count} words of narration (min {q.min_words})")

    if len(script.scenes) < q.min_scenes:
        reasons.append(f"only {len(script.scenes)} scenes (min {q.min_scenes})")

    if q.require_hook_and_insight:
        if not script.scenes or script.scenes[0].role != "hook":
            reasons.append("first scene is not role=hook")
        if not script.scenes or script.scenes[-1].role != "insight":
            reasons.append("last scene is not role=insight")

    seen_narration = {}
    for i, scene in enumerate(script.scenes):
        text = scene.narration.strip()
        lower = text.lower()

        if len(text.split()) < MIN_SCENE_WORDS:
            reasons.append(f"scene {i} narration is only {len(text.split())} word(s) (\"{text}\") - likely truncated output")

        normalized = " ".join(lower.split()).rstrip(".!?")
        if normalized and normalized in seen_narration:
            reasons.append(f"scene {i} narration is a duplicate of scene {seen_narration[normalized]}")
        elif normalized:
            seen_narration[normalized] = i

        if any(p in lower for p in _REFUSAL_PATTERNS):
            reasons.append(f"scene {i} narration looks like a refused/hedged LLM response, not real content")

        if any(a in text for a in _MARKDOWN_ARTIFACTS):
            reasons.append(f"scene {i} narration has leftover markdown formatting")

        if any(p in lower for p in _PLACEHOLDER_PATTERNS):
            reasons.append(f"scene {i} narration has a placeholder token, not real content")

    if script.scenes:
        hook_text = script.scenes[0].narration.strip().lower()
        if any(hook_text.startswith(o) for o in _WEAK_HOOK_OPENERS):
            reasons.append("hook scene opens with generic throat-clearing instead of delivering the title's promise")

    if not script.title.strip():
        reasons.append("title is empty")
    elif q.require_strong_hook and not _has_strong_hook_marker(script.title):
        reasons.append(
            "title doesn't use a strong hook shape (cause-and-effect, immersive daily-life "
            "curiosity, myth/legend, or hidden-truth reveal) - reads like a vague listicle "
            "or topic label instead"
        )

    if len(script.description.split()) < MIN_DESCRIPTION_WORDS:
        reasons.append(f"description is only {len(script.description.split())} words (min {MIN_DESCRIPTION_WORDS})")

    if len(script.tags) < MIN_TAGS:
        reasons.append(f"only {len(script.tags)} tags (min {MIN_TAGS})")

    return (len(reasons) == 0, reasons)


def _ffprobe_streams(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-show_entries", "stream=codec_type,width,height,r_frame_rate",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def _parse_frame_rate(r_frame_rate: "str | None") -> "float | None":
    if not r_frame_rate or "/" not in r_frame_rate:
        return None
    num, _, den = r_frame_rate.partition("/")
    try:
        num, den = float(num), float(den)
        return num / den if den else None
    except ValueError:
        return None


def _mean_volume_db(path: Path) -> "float | None":
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    for line in result.stderr.splitlines():
        if "mean_volume:" in line:
            try:
                return float(line.split("mean_volume:")[1].strip().split(" ")[0])
            except ValueError:
                return None
    return None


def check_media(
    video_path: Path, all_scene_audio: List[SceneAudio], captions_path: "Path | None", config: PipelineConfig,
) -> Tuple[bool, List[str]]:
    """Inspects the actually-rendered final.mp4 (and captions file) rather
    than trusting every upstream step worked - see module docstring."""
    reasons: List[str] = []

    if not video_path.exists() or video_path.stat().st_size == 0:
        return False, ["final video file is missing or empty"]

    probe = _ffprobe_streams(video_path)
    streams = probe.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    if not video_streams:
        reasons.append("rendered file has no video stream")
    else:
        w, h = video_streams[0].get("width"), video_streams[0].get("height")
        expected_w, expected_h = config.video.resolution
        if (w, h) != (expected_w, expected_h):
            reasons.append(f"rendered resolution {w}x{h} doesn't match configured {expected_w}x{expected_h}")

        fps = _parse_frame_rate(video_streams[0].get("r_frame_rate"))
        if fps is None:
            reasons.append("could not determine rendered frame rate")
        elif abs(fps - config.video.fps) > 1.0:
            reasons.append(f"rendered frame rate {fps:.1f}fps doesn't match configured {config.video.fps}fps")

    if not audio_streams:
        reasons.append("rendered file has no audio stream (silent video)")

    expected_duration = sum(a.duration for a in all_scene_audio)
    try:
        actual_duration = float(probe.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        actual_duration = 0.0
    drift = abs(actual_duration - expected_duration)
    if actual_duration <= 0:
        reasons.append("could not determine rendered video duration")
    elif drift > max(MAX_DURATION_DRIFT_SECONDS, expected_duration * MAX_DURATION_DRIFT_FRACTION):
        reasons.append(
            f"rendered duration {actual_duration:.1f}s doesn't match expected {expected_duration:.1f}s "
            f"(drift {drift:.1f}s) - possible truncated/corrupted render"
        )

    if audio_streams:
        mean_db = _mean_volume_db(video_path)
        if mean_db is None:
            reasons.append("could not measure audio loudness")
        elif mean_db < MIN_MEAN_VOLUME_DB:
            reasons.append(f"audio mix is effectively silent (mean_volume={mean_db:.1f}dB, min {MIN_MEAN_VOLUME_DB}dB)")

    if captions_path is not None:
        if not captions_path.exists() or captions_path.stat().st_size == 0:
            reasons.append("captions file is missing or empty")
        elif "Dialogue:" not in captions_path.read_text(encoding="utf-8", errors="ignore"):
            reasons.append("captions file has no caption lines (word-timing data may have failed)")

    if reasons:
        logger.warning("Media quality gate failed: %s", "; ".join(reasons))
    return (len(reasons) == 0, reasons)
