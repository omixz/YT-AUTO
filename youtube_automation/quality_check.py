"""A cheap heuristic gate that runs before upload.

This doesn't fact-check or judge whether a script is *good* - it just catches
the failure mode where a run produces something too thin to plausibly read
as produced content (which is exactly what YouTube's reused/duplicative
content policy targets): too few words, too few scenes, or missing the
hook/insight structure the script prompt was told to follow.

A failing script still gets built and uploaded (never silently dropped) -
it's just uploaded under quality.fallback_privacy_status instead of the
configured public/unlisted default, so a weak episode doesn't go out
unattended and you can decide by hand whether to publish it.
"""
from __future__ import annotations

from typing import List, Tuple

from .config import PipelineConfig
from .script_writer import Script


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

    return (len(reasons) == 0, reasons)
