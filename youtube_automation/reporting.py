"""Generates a per-video performance report once a video's stats mature.

Each report (reports/<published_at>-<video_id>.md) answers two questions:
what worked for this video, and what specifically to do to get more views
next time - broken down by every traffic source YouTube exposes (search,
suggested, browse/home, shorts feed, external, playlists, notifications,
...), since each source has a different lever: search wants keywords,
suggested wants topical adjacency + retention, browse wants CTR, external
wants off-platform sharing.

Numbers are only meaningful relative to the channel's own history, so every
report compares against the running channel averages accumulated in
reports/history.json, and the recommendations are rule-based (no API cost)
with thresholds tuned to small-channel realities rather than big-channel
benchmarks.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from googleapiclient.discovery import build

from .config import ROOT, PipelineConfig
from .youtube_auth import get_credentials

logger = logging.getLogger(__name__)

REPORTS_DIR = "reports"
HISTORY_FILE = "history.json"

# YouTube Analytics insightTrafficSourceType values -> human labels and the
# lever that actually moves each one.
_TRAFFIC_SOURCES = {
    "YT_SEARCH": (
        "YouTube search",
        "Put the exact phrases people search for in the title/description; front-load the main keyword.",
    ),
    "RELATED_VIDEO": (
        "Suggested videos",
        "Retention drives this: stronger hooks, faster pacing, and topics adjacent to big channels' hits.",
    ),
    "BROWSE": (
        "Browse / home feed",
        "This is a thumbnail+title CTR game - bolder curiosity gaps, cleaner thumbnails.",
    ),
    "SHORTS": (
        "Shorts feed",
        "First 2 seconds decide everything - open on the most shocking beat, no setup.",
    ),
    "EXT_URL": (
        "External links",
        "Share to relevant subreddits/forums/Discords where the topic already has an audience.",
    ),
    "NOTIFICATION": (
        "Subscriber notifications",
        "Grows with subscriber count - consistent niches + end-screen subscribe CTAs compound this.",
    ),
    "PLAYLIST": (
        "Playlists",
        "Group videos into topical playlists so one view chains into the next.",
    ),
    "SUBSCRIBER": (
        "Subscriptions feed",
        "Grows with subscriber count - keep formats consistent so subscribers know what they're getting.",
    ),
    "YT_CHANNEL": (
        "Channel page",
        "Channel page visitors browse; a coherent niche + strong recent uploads convert them.",
    ),
    "YT_OTHER_PAGE": ("Other YouTube pages", "Low-leverage; no direct action."),
    "NO_LINK_OTHER": ("Direct / unknown", "Low-leverage; no direct action."),
}


def _reports_dir() -> Path:
    return ROOT / REPORTS_DIR


def _load_history() -> List[dict]:
    path = _reports_dir() / HISTORY_FILE
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _save_history(history: List[dict]) -> None:
    path = _reports_dir() / HISTORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2), encoding="utf-8")


def fetch_detailed_stats(
    video_id: str, published_at: dt.date, config: PipelineConfig, window_days: int,
) -> Optional[dict]:
    """Core metrics + a views-by-traffic-source breakdown for the first
    window_days after publish. Returns None if YouTube has no data yet."""
    creds = get_credentials(config)
    yt = build("youtubeAnalytics", "v2", credentials=creds)

    start = published_at.isoformat()
    end = (published_at + dt.timedelta(days=window_days)).isoformat()

    core = yt.reports().query(
        ids="channel==MINE",
        startDate=start,
        endDate=end,
        metrics=(
            "views,estimatedMinutesWatched,averageViewDuration,"
            "averageViewPercentage,likes,comments,shares,subscribersGained"
        ),
        filters=f"video=={video_id}",
    ).execute()

    rows = core.get("rows")
    if not rows:
        return None

    (views, minutes, avg_duration, avg_pct, likes, comments, shares, subs) = rows[0]
    stats = {
        "views": int(views),
        "minutes_watched": float(minutes),
        "avg_view_duration_s": float(avg_duration),
        "avg_view_percentage": float(avg_pct),
        "likes": int(likes),
        "comments": int(comments),
        "shares": int(shares),
        "subscribers_gained": int(subs),
    }

    sources = yt.reports().query(
        ids="channel==MINE",
        startDate=start,
        endDate=end,
        metrics="views",
        dimensions="insightTrafficSourceType",
        filters=f"video=={video_id}",
        sort="-views",
    ).execute()

    stats["traffic_sources"] = {
        row[0]: int(row[1]) for row in sources.get("rows") or []
    }
    return stats


def _channel_averages(history: List[dict]) -> Optional[dict]:
    if not history:
        return None
    n = len(history)
    keys = ("views", "avg_view_percentage", "subscribers_gained", "likes")
    return {k: sum(h["stats"].get(k, 0) for h in history) / n for k in keys}


def _vs_avg(value: float, avg: Optional[float]) -> str:
    if not avg:
        return ""
    delta = (value - avg) / avg * 100 if avg else 0.0
    return f" ({'+' if delta >= 0 else ''}{delta:.0f}% vs channel avg)"


def _recommendations(stats: dict, avgs: Optional[dict], record: dict) -> List[str]:
    recs: List[str] = []
    views = stats["views"]
    retention = stats["avg_view_percentage"]
    sources = stats.get("traffic_sources", {})

    # Retention is the single biggest lever for suggested/browse reach.
    if retention < 30:
        recs.append(
            f"Retention is low ({retention:.0f}% average watched): tighten the hook so the first "
            "sentence pays off the title's promise, and cut any scene that doesn't advance the story."
        )
    elif retention >= 50:
        recs.append(
            f"Retention is strong ({retention:.0f}% average watched) - this topic/style combination "
            "works; queue more topics like this one."
        )

    if avgs and views > avgs["views"] * 1.5 and len(sources) > 0:
        top = max(sources, key=sources.get)
        label = _TRAFFIC_SOURCES.get(top, (top, ""))[0]
        recs.append(
            f"This video beat the channel average on views, driven mostly by {label} - "
            "study what it did differently (topic, title shape, thumbnail) and repeat it."
        )
    if avgs and views < avgs["views"] * 0.5:
        recs.append(
            "This video underperformed the channel average - if the pattern repeats for this "
            "niche, the bandit will down-weight it automatically, but consider retiring this "
            "topic angle sooner."
        )

    # Source-mix gaps: search and suggested are where compounding growth lives.
    total_source_views = sum(sources.values()) or 1
    search_share = sources.get("YT_SEARCH", 0) / total_source_views
    suggested_share = sources.get("RELATED_VIDEO", 0) / total_source_views
    if search_share < 0.15:
        recs.append(
            "Search is a small share of views: work searchable phrases into titles "
            "(what would someone actually type?) and the first two description lines."
        )
    if suggested_share < 0.15:
        recs.append(
            "Suggested-video traffic is low: pick topics adjacent to videos that are already "
            "big in this niche so YouTube has somewhere to recommend this next to."
        )

    if stats["subscribers_gained"] == 0 and views > 50:
        recs.append(
            "Views but zero subscribers gained: strengthen the outro CTA or give a concrete "
            "reason to subscribe ('every week, another mystery')."
        )

    if not recs:
        recs.append("Too little data to draw conclusions yet - keep publishing on schedule.")
    return recs


def _render_markdown(record: dict, stats: dict, avgs: Optional[dict], window_days: int) -> str:
    title = record.get("title") or "(title not recorded)"
    lines = [
        f"# Video report: {title}",
        "",
        f"- **Video:** https://youtu.be/{record['video_id']}",
        f"- **Niche / format:** {record['niche']} / {record['format']}",
        f"- **Published:** {record['published_at']} (stats window: first {window_days} days)",
        "",
        "## Performance",
        "",
        f"- Views: **{stats['views']}**{_vs_avg(stats['views'], avgs and avgs['views'])}",
        f"- Average watched: **{stats['avg_view_percentage']:.0f}%** "
        f"({stats['avg_view_duration_s']:.0f}s)"
        f"{_vs_avg(stats['avg_view_percentage'], avgs and avgs['avg_view_percentage'])}",
        f"- Watch time: **{stats['minutes_watched']:.0f} min**",
        f"- Subscribers gained: **{stats['subscribers_gained']}**"
        f"{_vs_avg(stats['subscribers_gained'], avgs and avgs['subscribers_gained'])}",
        f"- Likes / comments / shares: {stats['likes']} / {stats['comments']} / {stats['shares']}",
        "",
        "## Where the views came from",
        "",
    ]

    sources = stats.get("traffic_sources", {})
    if sources:
        total = sum(sources.values()) or 1
        lines.append("| Source | Views | Share | How to get more from it |")
        lines.append("|---|---|---|---|")
        for src, count in sorted(sources.items(), key=lambda kv: -kv[1]):
            label, lever = _TRAFFIC_SOURCES.get(src, (src, "-"))
            lines.append(f"| {label} | {count} | {count / total * 100:.0f}% | {lever} |")
    else:
        lines.append("No traffic-source data reported yet.")

    lines += ["", "## What to do next", ""]
    lines += [f"- {rec}" for rec in _recommendations(stats, avgs, record)]
    lines.append("")
    return "\n".join(lines)


def generate_report(record: dict, config: PipelineConfig, window_days: int) -> Optional[Path]:
    """Fetches detailed stats for one published-video ledger record and
    writes its markdown report. Returns None if stats aren't available yet."""
    published = dt.date.fromisoformat(record["published_at"])
    stats = fetch_detailed_stats(record["video_id"], published, config, window_days)
    if stats is None:
        return None

    # Averages are computed from history *before* this video is appended, so
    # a video is compared against the channel as it stood when it launched.
    history = _load_history()
    avgs = _channel_averages(history)

    report_md = _render_markdown(record, stats, avgs, window_days)
    out_path = _reports_dir() / f"{record['published_at']}-{record['video_id']}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report_md, encoding="utf-8")

    history.append({
        "video_id": record["video_id"],
        "published_at": record["published_at"],
        "niche": record["niche"],
        "format": record["format"],
        "title": record.get("title"),
        "stats": stats,
    })
    _save_history(history)

    logger.info("Wrote report %s", out_path)
    return out_path
