"""Picks when a video should actually go live, decoupled from whenever the
build happens to finish.

Research on YouTube posting times consistently points to early-to-mid
afternoon Eastern Time on Wednesday/Thursday as the strongest slot for
documentary/long-form content - posting a few hours ahead of the evening
peak gives the algorithm time to index and start surfacing the video right
as traffic ramps up. Build time varies a lot in practice (a longform run can
take anywhere from ~10 to 40+ minutes depending on image-gen latency), so
rather than publishing immediately whenever the pipeline happens to finish,
every run schedules the upload for the next optimal slot via YouTube's
native publishAt.
"""
from __future__ import annotations

import datetime as dt

# 17:00 UTC sits inside the 12-3pm ET window across both EST and EDT.
TARGET_HOUR_UTC = 17
TARGET_WEEKDAYS = {2, 3}  # Wednesday=2, Thursday=3 (Monday=0)
MIN_LEAD_TIME = dt.timedelta(hours=2)  # YouTube requires publishAt to be in the future


def next_optimal_publish_time(now: "dt.datetime | None" = None) -> str:
    """Returns an RFC3339 UTC timestamp for the next Wednesday or Thursday at
    17:00 UTC that's at least MIN_LEAD_TIME away, so a slow build never
    lands so close to the target that YouTube rejects the scheduled time."""
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    earliest = now + MIN_LEAD_TIME

    candidate = now.replace(hour=TARGET_HOUR_UTC, minute=0, second=0, microsecond=0)
    for _ in range(14):
        if candidate.weekday() in TARGET_WEEKDAYS and candidate >= earliest:
            return candidate.strftime("%Y-%m-%dT%H:%M:%SZ")
        candidate += dt.timedelta(days=1)

    raise RuntimeError("could not find a valid optimal publish slot within 14 days")
