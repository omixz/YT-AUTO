#!/usr/bin/env python3
"""Rolls up YouTube Analytics data for videos that have matured since
publish (config.growth.maturity_days) into config/performance_stats.json,
which niche_selector.py reads to bias future (niche, format) choices toward
what's actually working.

Meant to run on its own schedule, separate from run_pipeline.py - a video's
stats aren't meaningful until they've had time to settle, so this is a
distinct cron in .github/workflows/sync_analytics.yml rather than a step
tacked onto every publish run.
"""
from __future__ import annotations

import datetime as dt
import logging
import sys

from youtube_automation import analytics, growth_ledger, reporting
from youtube_automation.config import PipelineConfig


def _describe(exc: Exception) -> str:
    """One-line, human-readable cause. For Google API errors this includes the
    HTTP status and reason (e.g. 403 accessNotConfigured / insufficientPermissions)."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    content = getattr(exc, "content", b"")
    if isinstance(content, bytes):
        content = content.decode("utf-8", "replace")
    detail = f" status={status} body={str(content)[:400]}" if status else ""
    return f"{type(exc).__name__}: {exc}{detail}".replace("\n", " ")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logger = logging.getLogger("sync_analytics")

    config = PipelineConfig.load()
    records = growth_ledger.unscored_mature_records(config)
    logger.info("%d matured, unscored video(s) to check.", len(records))

    failures: list = []
    for record in records:
        published = dt.date.fromisoformat(record["published_at"])
        try:
            stats = analytics.fetch_video_stats(
                record["video_id"], published, config, window_days=config.growth.maturity_days
            )
        except Exception as exc:  # noqa: BLE001 - surface the real cause, keep scoring the rest
            failures.append((record["video_id"], _describe(exc)))
            logger.exception("Analytics fetch failed for %s - continuing.", record["video_id"])
            continue
        if stats is None:
            logger.warning("No analytics data yet for %s - will retry next sync.", record["video_id"])
            continue

        growth_ledger.apply_score(config, record["niche"], record["format"], stats.score)
        growth_ledger.mark_scored(record["video_id"])
        logger.info(
            "Scored %s (%s/%s): score=%.1f (views=%d, minutes_watched=%.1f, subs_gained=%d)",
            record["video_id"], record["niche"], record["format"], stats.score,
            stats.views, stats.estimated_minutes_watched, stats.subscribers_gained,
        )

        # Post-mortem report: what worked, and how to get more views next
        # time, broken down per traffic source - see reporting.py. A report
        # failure shouldn't block scoring the remaining videos.
        try:
            reporting.generate_report(record, config, window_days=config.growth.maturity_days)
        except Exception:
            logger.exception("Report generation failed for %s - continuing.", record["video_id"])


    if failures:
        for vid, why in failures:
            # GitHub Actions turns this into a visible annotation on the run.
            print(f"::error title=Analytics sync failed for {vid}::{why}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"::error title=Analytics sync crashed::{_describe(exc)}")
        raise
