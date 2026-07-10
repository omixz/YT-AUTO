"""Tracks published videos (config/published_videos.json) so sync_analytics.py
knows what to score once it's matured, and rolls scored results into
config/performance_stats.json for niche_selector.py to read.

Kept under config/ (not output/) specifically so it survives across ephemeral
CI runners via the same git-commit-back mechanism as the topic queues.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import List

from .config import ROOT, PipelineConfig
from .niche_selector import stats_key

LEDGER_PATH = "config/published_videos.json"


def _load(path: Path) -> List[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, records: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2), encoding="utf-8")


def record_published(niche_key: str, format_name: str, video_id: str) -> None:
    path = ROOT / LEDGER_PATH
    records = _load(path)
    records.append({
        "video_id": video_id,
        "niche": niche_key,
        "format": format_name,
        "published_at": dt.date.today().isoformat(),
        "scored": False,
    })
    _save(path, records)


def unscored_mature_records(config: PipelineConfig) -> List[dict]:
    records = _load(ROOT / LEDGER_PATH)
    today = dt.date.today()
    mature = []
    for r in records:
        if r.get("scored"):
            continue
        published = dt.date.fromisoformat(r["published_at"])
        if (today - published).days >= config.growth.maturity_days:
            mature.append(r)
    return mature


def mark_scored(video_id: str) -> None:
    path = ROOT / LEDGER_PATH
    records = _load(path)
    for r in records:
        if r["video_id"] == video_id:
            r["scored"] = True
    _save(path, records)


def apply_score(config: PipelineConfig, niche_key: str, format_name: str, score: float) -> None:
    stats_path = ROOT / config.growth.stats_file
    stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else {}

    key = stats_key(niche_key, format_name)
    entry = stats.get(key, {"samples": 0, "total_score": 0.0, "avg_score": 0.0})
    entry["samples"] += 1
    entry["total_score"] += score
    entry["avg_score"] = entry["total_score"] / entry["samples"]
    stats[key] = entry

    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
