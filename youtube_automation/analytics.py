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
