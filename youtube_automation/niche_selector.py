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

TREND DETECTION & SEASONAL AWARENESS:
- Rolling 7-day and 30-day performance windows detect rising/falling niches
- Seasonal multipliers boost niches that historically perform well in current month
- Competitor gap analysis identifies underserved topic areas per niche
- Topic freshness scoring penalizes recently-covered similar topics
"""
from __future__ import annotations

import calendar
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from .config import ROOT, PipelineConfig


# Seasonal affinity: niche -> months where it performs best (1-12)
# Based on real YouTube seasonal patterns: history spikes in summer/Jan, tech in Q4, etc.
SEASONAL_AFFINITY: Dict[str, List[int]] = {
    "history": [1, 6, 7, 11, 12],      # New Year resolutions, summer learning, holidays
    "science": [3, 9, 10],             # Spring curiosity, back-to-school, Nobel season
    "technology": [4, 10, 11, 12],     # Spring launches, Q4 buying guides, year-in-review
    "finance": [1, 4, 10],             # New Year resolutions, tax season, year-end planning
    "health": [1, 5, 9],               # New Year, summer body, back-to-school
    "true_crime": [2, 10, 11],         # Valentine's, Halloween season, holiday binge
    "mythology": [3, 10, 12],          # Spring renewal, Halloween myths, winter stories
    "war": [5, 6, 11],                 # Memorial Day, D-Day, Veterans Day
    "default": list(range(1, 13)),      # No seasonal bias
}

# Trend window sizes (days)
TREND_WINDOWS = [7, 30]


def stats_key(niche_key: str, format_name: str) -> str:
    return f"{niche_key}:{format_name}"


def _load_stats(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_topic_history(path: Path) -> List[str]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _enabled_combos(config: PipelineConfig) -> List[Tuple[str, str, float]]:
    combos = []
    for niche in config.niches:
        for format_name, format_cfg in config.video.formats.items():
            if format_cfg.enabled:
                combos.append((niche.key, format_name, niche.weight * format_cfg.weight))
    return combos


def _seasonal_multiplier(niche_key: str, month: int) -> float:
    """Returns >1.0 for in-season months, <1.0 for off-season, 1.0 neutral."""
    # Extract base niche name (strip any prefix)
    base_niche = niche_key.split("_")[-1].lower()
    affinity_months = SEASONAL_AFFINITY.get(base_niche, SEASONAL_AFFINITY["default"])
    if month in affinity_months:
        return 1.3  # 30% boost in peak months
    # Check adjacent months for shoulder season
    for m in affinity_months:
        if abs((m - month) % 12) == 1:
            return 1.1
    return 1.0


def _trend_score(stats: dict, niche_key: str, format_name: str) -> float:
    """Compute trend from rolling windows. Positive = improving, negative = declining."""
    key = stats_key(niche_key, format_name)
    data = stats.get(key, {})
    
    # Require enough data for trend
    if data.get("samples", 0) < 5:
        return 0.0
    
    # Check if we have windowed scores
    windows = data.get("windows", {})
    if not windows:
        return 0.0
    
    # Compare 7-day vs 30-day average
    recent_7 = windows.get("7d", {}).get("avg_score", 0.0)
    recent_30 = windows.get("30d", {}).get("avg_score", 0.0)
    
    if recent_30 == 0:
        return 0.0
    
    # Normalized trend: (7d - 30d) / 30d
    return (recent_7 - recent_30) / recent_30


def _competitor_gap_score(niche_key: str, recent_topics: List[str]) -> float:
    """Heuristic: penalize overdone topic patterns, reward gaps.
    This is a lightweight version - real implementation would query YouTube API."""
    if not recent_topics:
        return 1.0
    
    # Simple keyword diversity check
    keywords = set()
    for topic in recent_topics[-20:]:
        words = topic.lower().split()
        keywords.update(w for w in words if len(w) > 4)
    
    # Higher score = more diverse = less saturated
    diversity = len(keywords) / max(1, len(recent_topics))
    return min(1.5, max(0.5, diversity * 2))


def _topic_freshness(topic: str, history: List[str]) -> float:
    """Score how fresh a topic is relative to recent history. Higher = fresher."""
    if not history:
        return 1.0
    
    topic_lower = topic.lower()
    topic_words = set(topic_lower.split())
    
    # Check similarity to recent topics (last 10)
    max_similarity = 0.0
    for recent in history[-10:]:
        recent_words = set(recent.lower().split())
        if topic_words and recent_words:
            intersection = topic_words & recent_words
            union = topic_words | recent_words
            jaccard = len(intersection) / len(union)
            max_similarity = max(max_similarity, jaccard)
    
    # Invert: low similarity = high freshness
    return 1.0 - max_similarity * 0.8


def choose(config: PipelineConfig, format_override: "str | None" = None) -> Tuple[str, str]:
    """Returns (niche_key, format_name). format_override forces a specific
    format (e.g. for a one-off manual run) while still letting the bandit
    pick the niche normally - see run_pipeline.py's --format flag."""
    combos = _enabled_combos(config)
    if not combos:
        raise RuntimeError(
            "No enabled (niche, format) combinations - check channel.yaml's "
            "niches: list and video.formats: entries."
        )

    if format_override:
        combos = [c for c in combos if c[1] == format_override]
        if not combos:
            raise RuntimeError(
                f"format_override={format_override!r} doesn't match any enabled "
                "(niche, format) combination."
            )

    stats = _load_stats(ROOT / config.growth.stats_file)
    current_month = datetime.now().month

    def samples(niche_key: str, format_name: str) -> int:
        return stats.get(stats_key(niche_key, format_name), {}).get("samples", 0)

    def avg_score(niche_key: str, format_name: str) -> float:
        return stats.get(stats_key(niche_key, format_name), {}).get("avg_score", 0.0)

    trusted = [
        (n, f) for (n, f, _w) in combos
        if samples(n, f) >= config.growth.min_samples_for_trust
    ]

    if trusted and random.random() > config.growth.epsilon:
        # Exploit with trend + seasonal awareness
        def combo_score(combo):
            n, f = combo
            base = avg_score(n, f)
            trend = _trend_score(stats, n, f)
            seasonal = _seasonal_multiplier(n, current_month)
            return base * seasonal * (1 + trend * 0.5)  # trend has 50% weight
        
        return max(trusted, key=combo_score)

    # Explore: weighted-random, favoring combos with fewer samples
    weights = [w / (1 + samples(n, f)) for (n, f, w) in combos]
    niche_key, format_name, _w = random.choices(combos, weights=weights, k=1)[0]
    return niche_key, format_name


def choose_topic_with_intelligence(
    config: PipelineConfig,
    niche_key: str,
    candidate_topics: List[str],
    history: List[str],
) -> str:
    """Select the best topic from candidates using trend, seasonal, gap, and freshness signals."""
    if not candidate_topics:
        return ""
    
    current_month = datetime.now().month
    seasonal = _seasonal_multiplier(niche_key, current_month)
    gap = _competitor_gap_score(niche_key, history)
    
    best_topic = candidate_topics[0]
    best_score = -1.0
    
    for topic in candidate_topics:
        freshness = _topic_freshness(topic, history)
        # Combined score: seasonal * gap * freshness
        score = seasonal * gap * freshness
        if score > best_score:
            best_score = score
            best_topic = topic
    
    return best_topic
