"""Tracks which topics have already been produced and picks the next one."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import yaml

from .config import ROOT, PipelineConfig
from .script_writer import brainstorm_topics


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


def _save_queue(path: Path, topics: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"topics": topics}, sort_keys=False), encoding="utf-8")


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

    if not queue:
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
