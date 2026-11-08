"""Tracks which topics have already been produced and picks the next one."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import yaml

from .config import ROOT, PipelineConfig
from .script_writer import brainstorm_topics, brainstorm_trending_topics

import logging

logger = logging.getLogger(__name__)


def _load_history(path: Path) -> List[str]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _save_history(path: Path, history: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2), encoding="utf-8")


def _load_queue(path: Path) -> List[str]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(raw.get("topics") or [])


def _load_priority(path: Path) -> List[str]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(raw.get("priority") or [])


def _save_queue(path: Path, topics: List[str], priority: "List[str] | None" = None) -> None:
    """`priority` (optional) is the follow-up lane for breakout videos; it is kept as-is when not passed."""
    if priority is None:
        priority = _load_priority(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"priority": priority, "topics": topics} if priority else {"topics": topics}
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def push_priority(config: PipelineConfig, niche_key: str, topics: List[str]) -> int:
    """Queue follow-up topics ahead of the normal queue for this niche. Returns how many were added."""
    queue_path = ROOT / config.topics.queue_file.format(niche=niche_key)
    history = {t.lower() for t in _load_history(ROOT / config.topics.history_file.format(niche=niche_key))}
    priority = _load_priority(queue_path)
    known = history | {t.lower() for t in priority}
    new = [t for t in topics if t and t.lower() not in known]
    _save_queue(queue_path, _load_queue(queue_path), priority + new)
    return len(new)


def next_topic(config: PipelineConfig, niche_key: str, override: Optional[str] = None) -> str:
    """Pop the next topic off niche_key's queue, brainstorming more via Gemini if empty.

    Each niche gets its own queue/history file (config.topics.queue_file /
    history_file are `{niche}`-templated paths) so topics never cross-pollinate
    between niches sharing the one channel.

    Uses intelligent selection: trend detection, seasonal awareness, competitor
    gap analysis, and topic freshness to pick the best candidate from the queue.
    """
    if override:
        return override

    queue_path = ROOT / config.topics.queue_file.format(niche=niche_key)
    history_path = ROOT / config.topics.history_file.format(niche=niche_key)

    queue = _load_queue(queue_path)
    history = _load_history(history_path)

    priority = _load_priority(queue_path)
    if priority:
        # Follow-ups to a breakout video go first, in order: no freshness re-ranking (it would penalise exactly the
        # similarity to the winner that makes them worth making).
        topic = priority.pop(0)
        _save_queue(queue_path, queue, priority)
        history.append(topic)
        _save_history(history_path, history)
        logger.info("Using a follow-up topic queued after a breakout video (%d more waiting).", len(priority))
        return topic

    if not queue:
        if config.topics.use_trending:
            try:
                queue = brainstorm_trending_topics(config, existing=history, count=5)
                logger.info("Brainstormed %d topic(s) from real current trending stories.", len(queue))
            except Exception as exc:
                # A grounding hiccup (Google Search tool unavailable, no
                # genuinely-fitting trends found this run, etc.) shouldn't
                # take down the whole scheduled run - fall back to the
                # un-grounded brainstorm, same as before this feature existed.
                logger.warning("Trending topic brainstorm failed (%s) - falling back to regular brainstorm.", exc)
                queue = brainstorm_topics(config, existing=history, count=5)
        else:
            queue = brainstorm_topics(config, existing=history, count=5)

    # Intelligent selection: if we have multiple candidates, pick the best one
    # based on seasonal trends, competitor gaps, and topic freshness.
    if len(queue) > 1:
        from .niche_selector import choose_topic_with_intelligence
        topic = choose_topic_with_intelligence(config, niche_key, queue, history)
        queue.remove(topic)
    else:
        topic = queue.pop(0)
    
    _save_queue(queue_path, queue)

    history.append(topic)
    _save_history(history_path, history)

    return topic
