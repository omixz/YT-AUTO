import datetime as dt

from youtube_automation.scheduling import next_optimal_publish_time


def test_picks_todays_slot_when_early_enough():
    now = dt.datetime(2026, 7, 13, 10, 0, tzinfo=dt.timezone.utc)  # Monday morning
    assert next_optimal_publish_time(now) == "2026-07-13T17:00:00Z"


def test_same_day_if_still_enough_lead_time():
    now = dt.datetime(2026, 7, 15, 10, 0, tzinfo=dt.timezone.utc)
    assert next_optimal_publish_time(now) == "2026-07-15T17:00:00Z"


def test_skips_to_next_day_if_too_close():
    now = dt.datetime(2026, 7, 15, 16, 30, tzinfo=dt.timezone.utc)  # <2h before 17:00
    assert next_optimal_publish_time(now) == "2026-07-16T17:00:00Z"


def test_skips_to_next_day_when_already_past_slot():
    now = dt.datetime(2026, 7, 16, 20, 0, tzinfo=dt.timezone.utc)  # evening, past today's 17:00
    assert next_optimal_publish_time(now) == "2026-07-17T17:00:00Z"


def test_every_consecutive_day_gets_a_slot():
    # Daily cadence: each day's slot should be exactly 24h after the previous.
    now = dt.datetime(2026, 7, 13, 10, 0, tzinfo=dt.timezone.utc)
    first = dt.datetime.strptime(next_optimal_publish_time(now), "%Y-%m-%dT%H:%M:%SZ")
    second_now = first.replace(tzinfo=dt.timezone.utc) + dt.timedelta(hours=3)  # just past today's slot
    second = dt.datetime.strptime(next_optimal_publish_time(second_now), "%Y-%m-%dT%H:%M:%SZ")
    assert (second - first).days == 1
