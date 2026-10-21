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


def record_published(
    niche_key: str, format_name: str, video_id: str,
    title: str = "", topic: str = "",
    privacy_status: str = "", passed_quality_gate: "bool | None" = None,
    quality_gate_reasons: "List[str] | None" = None,
    render: "dict | None" = None,
) -> None:
    # Title/topic are captured here because the analytics token's scopes
    # can't read video metadata back from the Data API later - reporting.py
    # needs them when it writes the post-mortem report at maturity.
    #
    # privacy_status/passed_quality_gate/quality_gate_reasons are captured
    # for a different reason: a quality-gate failure still uploads and still
    # reaches this call (see pipeline.py) - it just uploads under
    # quality.fallback_privacy_status (typically "private") instead of the
    # configured public/unlisted default. Without recording that here, this
    # ledger makes a silently-private, gate-failed upload look identical to
    # a genuinely public one - "published" either way - so a real "why isn't
    # this video showing up on the channel" report has no state in the repo
    # to check against, only guesswork.
    path = ROOT / LEDGER_PATH
    records = _load(path)
    records.append({
        "video_id": video_id,
        "niche": niche_key,
        "format": format_name,
        "title": title,
        "topic": topic,
        "published_at": dt.date.today().isoformat(),
        "scored": False,
        "privacy_status": privacy_status,
        "passed_quality_gate": passed_quality_gate,
        "quality_gate_reasons": quality_gate_reasons or [],
        # which voice/animation engine really produced this video (and any fallbacks) - readable from the repo
        "render": render or {},
    })
    _save(path, records)


def is_scorable(record: dict) -> bool:
    """A video the public could actually watch. Gate-failed uploads go up as PRIVATE and get zero views,
    so scoring them would teach the bandit that the *niche* is bad when only the pipeline failed (mythology
    had 8 of 13 scored videos private, which made its average look 3x worse than its public videos)."""
    return record.get("privacy_status") != "private" and record.get("passed_quality_gate") is not False


def unscored_mature_records(config: PipelineConfig) -> List[dict]:
    records = _load(ROOT / LEDGER_PATH)
    today = dt.date.today()
    mature = []
    for r in records:
        if r.get("scored") or not is_scorable(r):
            continue
        published = dt.date.fromisoformat(r["published_at"])
        if (today - published).days >= config.growth.maturity_days:
            mature.append(r)
    return mature


def mark_scored(video_id: str, extra: "dict | None" = None) -> None:
    path = ROOT / LEDGER_PATH
    records = _load(path)
    for r in records:
        if r["video_id"] == video_id:
            r["scored"] = True
            if extra:
                r.update(extra)
    _save(path, records)


def set_fields(video_id: str, fields: dict) -> None:
    path = ROOT / LEDGER_PATH
    records = _load(path)
    for r in records:
        if r["video_id"] == video_id:
            r.update(fields)
    _save(path, records)


def needs_ctr(config: PipelineConfig, limit: int = 30) -> List[dict]:
    """Public, mature videos that have never had their CTR looked up (newest first)."""
    today = dt.date.today()
    out = [r for r in _load(ROOT / LEDGER_PATH)
           if is_scorable(r) and "ctr_checked" not in r
           and (today - dt.date.fromisoformat(r["published_at"])).days >= config.growth.maturity_days]
    return sorted(out, key=lambda r: r["published_at"], reverse=True)[:limit]


def ctr_insights(records: List[dict]) -> dict:
    """Impression-weighted CTR sliced by things we control, so the next thumbnail/title experiment is data-driven."""
    import re as _re
    rows = [r for r in records if r.get("ctr") is not None and (r.get("impressions") or 0) > 0]

    def agg(key_fn) -> dict:
        acc: dict = {}
        for r in rows:
            k = key_fn(r)
            if k is None:
                continue
            a = acc.setdefault(k, [0.0, 0, 0])
            a[0] += r["ctr"] * r["impressions"]; a[1] += r["impressions"]; a[2] += 1
        return {k: {"ctr": round(v[0] / v[1], 4), "impressions": v[1], "videos": v[2]} for k, v in sorted(acc.items())}

    return {
        "videos_with_ctr": len(rows),
        "overall_ctr": round(sum(r["ctr"] * r["impressions"] for r in rows) / max(1, sum(r["impressions"] for r in rows)), 4) if rows else None,
        "by_niche": agg(lambda r: r["niche"]),
        "by_format": agg(lambda r: r["format"]),
        "by_thumbnail_style": agg(lambda r: ((r.get("render") or {}).get("thumbnail") or {}).get("style") or "legacy"),
        "by_title_has_year": agg(lambda r: "year" if _re.search(r"\b(1[0-9]{3}|20[0-2][0-9])\b", r.get("title", "")) else "no_year"),
        "by_title_is_question": agg(lambda r: "question" if r.get("title", "").rstrip().endswith("?") else "statement"),
        "by_title_length": agg(lambda r: "<=50" if len(r.get("title", "")) <= 50 else "51-70" if len(r.get("title", "")) <= 70 else ">70"),
    }


def apply_score(config: PipelineConfig, niche_key: str, format_name: str, score: float) -> None:
    stats_path = ROOT / config.growth.stats_file
    stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else {}

    key = stats_key(niche_key, format_name)
    entry = stats.get(key, {"samples": 0, "total_score": 0.0, "avg_score": 0.0, "history": []})
    entry.setdefault("history", [])
    entry["samples"] += 1
    entry["total_score"] += score
    entry["avg_score"] = entry["total_score"] / entry["samples"]

    # niche_selector._trend_score reads entry["windows"]["7d"/"30d"]["avg_score"]
    # to compare recent vs. longer-run performance - this used to never get
    # written anywhere, so that trend comparison always saw an empty dict and
    # silently evaluated to 0 (neutral) every time, regardless of how a niche
    # was actually trending. Keep a dated history (pruned to 30 days - windows
    # never need more) and derive both windows from it here.
    today = dt.date.today()
    entry["history"].append({"date": today.isoformat(), "score": score})
    cutoff_30 = today - dt.timedelta(days=30)
    entry["history"] = [h for h in entry["history"] if dt.date.fromisoformat(h["date"]) >= cutoff_30]

    def _window(days: int) -> dict:
        cutoff = today - dt.timedelta(days=days)
        scores = [h["score"] for h in entry["history"] if dt.date.fromisoformat(h["date"]) >= cutoff]
        return {"avg_score": sum(scores) / len(scores)} if scores else {}

    entry["windows"] = {"7d": _window(7), "30d": _window(30)}

    stats[key] = entry
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")


def repair_stats(stats: dict, records: List[dict], today: "dt.date | None" = None) -> dict:
    """One-time cleanup: drop the zero-score entries that came from private (gate-failed) videos that were
    scored before is_scorable() existed. Removes exactly as many zero entries per niche as there were
    scored-but-private ledger records, then recomputes samples/avg/windows."""
    today = today or dt.date.today()
    owed: dict = {}
    for r in records:
        if r.get("scored") and not is_scorable(r):
            key = stats_key(r["niche"], r["format"])
            owed[key] = owed.get(key, 0) + 1
    for key, n in owed.items():
        entry = stats.get(key)
        if not entry:
            continue
        removed = 0
        kept = []
        for h in entry["history"]:
            if removed < n and h["score"] < 0.5:
                removed += 1
                continue
            kept.append(h)
        entry["history"] = kept
        entry["samples"] = max(0, entry["samples"] - removed)
        entry["avg_score"] = entry["total_score"] / entry["samples"] if entry["samples"] else 0.0

        def _window(days: int) -> dict:
            cutoff = today - dt.timedelta(days=days)
            scores = [h["score"] for h in kept if dt.date.fromisoformat(h["date"]) >= cutoff]
            return {"avg_score": sum(scores) / len(scores)} if scores else {}

        entry["windows"] = {"7d": _window(7), "30d": _window(30)}
        entry["repaired_private_zeros"] = removed
    return stats
