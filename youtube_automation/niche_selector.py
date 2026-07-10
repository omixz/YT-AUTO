"""Picks which (niche, format) to produce this run.

This is the "growth maximization" half of the pipeline: analytics.py scores
already-published videos, sync_analytics.py rolls those scores up into
config/performance_stats.json keyed by "niche:format", and this module reads
that file to bias future runs toward whichever combination is actually
performing - while still spending a fraction of runs (growth.epsilon)
exploring, so a combination never gets abandoned on a small sample or starved
before it has enough data to judge fairly.

Cold start (no stats yet, or too few samples): falls back to weighted-random
using each niche/format's configured `weight` as a prior, favoring whichever
combinations have the fewest samples so far so every combination gets a fair
first look before the bandit starts exploiting.
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import List, Tuple

from .config import ROOT, PipelineConfig


def stats_key(niche_key: str, format_name: str) -> str:
    return f"{niche_key}:{format_name}"


def _load_stats(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _enabled_combos(config: PipelineConfig) -> List[Tuple[str, str, float]]:
    combos = []
    for niche in config.niches:
        for format_name, format_cfg in config.video.formats.items():
            if format_cfg.enabled:
                combos.append((niche.key, format_name, niche.weight * format_cfg.weight))
    return combos


def choose(config: PipelineConfig) -> Tuple[str, str]:
    """Returns (niche_key, format_name)."""
    combos = _enabled_combos(config)
    if not combos:
        raise RuntimeError(
            "No enabled (niche, format) combinations - check channel.yaml's "
            "niches: list and video.formats: entries."
        )

    stats = _load_stats(ROOT / config.growth.stats_file)

    def samples(niche_key: str, format_name: str) -> int:
        return stats.get(stats_key(niche_key, format_name), {}).get("samples", 0)

    def avg_score(niche_key: str, format_name: str) -> float:
        return stats.get(stats_key(niche_key, format_name), {}).get("avg_score", 0.0)

    trusted = [
        (n, f) for (n, f, _w) in combos
        if samples(n, f) >= config.growth.min_samples_for_trust
    ]

    if trusted and random.random() > config.growth.epsilon:
        return max(trusted, key=lambda combo: avg_score(*combo))

    # Explore: weighted-random, favoring combos with fewer samples so every
    # combination gets a fair shot before the bandit starts exploiting.
    weights = [w / (1 + samples(n, f)) for (n, f, w) in combos]
    niche_key, format_name, _w = random.choices(combos, weights=weights, k=1)[0]
    return niche_key, format_name
