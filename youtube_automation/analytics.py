"""Pulls per-video performance stats from the YouTube Analytics API so
sync_analytics.py can roll them up into config/performance_stats.json for
niche_selector.py to read.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

from googleapiclient.discovery import build

from .config import PipelineConfig
from .youtube_auth import get_credentials

API_SERVICE_NAME = "youtubeAnalytics"
API_VERSION = "v2"


@dataclass
class VideoStats:
    views: int
    estimated_minutes_watched: float
    average_view_duration: float
    subscribers_gained: int

    @property
    def score(self) -> float:
        """A single growth-oriented number to rank (niche, format) combos by.

        Weighted toward subscribers gained (the actual YPP-eligibility metric)
        and watch time (what YouTube's own recommender optimizes for), with
        raw views weighted lowest so one viral outlier doesn't dominate a
        niche's average forever.
        """
        return (
            self.subscribers_gained * 50
            + self.estimated_minutes_watched * 2
            + self.views * 0.1
        )


CTR_ERRORS: list = []   # filled by fetch_ctr_metrics so the sync can surface WHY lookups failed (as a readable annotation)


def _query(api, video_id, start, end, metrics, dimensions=None):
    kw = dict(ids="channel==MINE", startDate=start, endDate=end, metrics=metrics, filters=f"video=={video_id}")
    if dimensions:
        kw["dimensions"] = dimensions
    return api.reports().query(**kw).execute()


def fetch_ctr_metrics(video_id: str, published_at: dt.date, config: PipelineConfig, window_days: int = 7) -> Optional[dict]:
    """Thumbnail impressions + click-through rate (+ average view percentage) for the first window_days.
    Best-effort: tries the metric forms the API accepts, records every failure in CTR_ERRORS, returns None
    (never raises) so the rest of the sync is unaffected."""
    start, end = published_at.isoformat(), (published_at + dt.timedelta(days=window_days)).isoformat()
    try:
        api = build(API_SERVICE_NAME, API_VERSION, credentials=get_credentials(config))
    except Exception as exc:  # noqa: BLE001
        CTR_ERRORS.append(f"auth/build: {type(exc).__name__}: {exc}"[:300])
        return None
    out: dict = {}
    attempts = [("videoThumbnailImpressions,videoThumbnailImpressionsClickRate", "video"),
                ("videoThumbnailImpressions,videoThumbnailImpressionsClickRate", None),
                ("videoThumbnailImpressions,videoThumbnailImpressionsClickRate", "day")]
    for metrics, dims in attempts:
        try:
            rows = _query(api, video_id, start, end, metrics, dims).get("rows") or []
            if rows:
                row = rows[0][1:] if dims == "video" else rows[0]
                if dims == "day":   # one row per day: impression-weighted
                    imp = sum(r[1] for r in rows)
                    out = {"impressions": int(imp), "ctr": round(sum(r[1] * r[2] for r in rows) / imp, 4) if imp else 0.0}
                else:
                    out = {"impressions": int(row[0]), "ctr": round(float(row[1]), 4)}
                break
        except Exception as exc:  # noqa: BLE001
            body = getattr(getattr(exc, "resp", None), "status", "") or ""
            CTR_ERRORS.append(f"{metrics.split(',')[0]} dims={dims}: {type(exc).__name__} {body} {str(exc)[:200]}")
    try:   # separate query: some metric groups can't be combined with impressions
        rows = _query(api, video_id, start, end, "averageViewPercentage").get("rows") or []
        if rows:
            out["avg_view_pct"] = round(float(rows[0][0]), 1)
    except Exception as exc:  # noqa: BLE001
        CTR_ERRORS.append(f"averageViewPercentage: {type(exc).__name__} {str(exc)[:160]}")
    return out or None


def fetch_video_stats(
    video_id: str, published_at: dt.date, config: PipelineConfig, window_days: int = 7,
) -> Optional[VideoStats]:
    """Stats for the first window_days after publish. Returns None if
    YouTube has no data for this video yet (e.g. queried too soon)."""
    creds = get_credentials(config)
    youtube_analytics = build(API_SERVICE_NAME, API_VERSION, credentials=creds)

    start_date = published_at.isoformat()
    end_date = (published_at + dt.timedelta(days=window_days)).isoformat()

    response = youtube_analytics.reports().query(
        ids="channel==MINE",
        startDate=start_date,
        endDate=end_date,
        metrics="views,estimatedMinutesWatched,averageViewDuration,subscribersGained",
        filters=f"video=={video_id}",
    ).execute()

    rows = response.get("rows")
    if not rows:
        return None

    views, minutes_watched, avg_duration, subs_gained = rows[0]
    return VideoStats(
        views=int(views),
        estimated_minutes_watched=float(minutes_watched),
        average_view_duration=float(avg_duration),
        subscribers_gained=int(subs_gained),
    )
