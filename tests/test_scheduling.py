import datetime as dt

from youtube_automation.scheduling import next_optimal_publish_time


def test_picks_next_wednesday_from_monday():
    now = dt.datetime(2026, 7, 13, 10, 0, tzinfo=dt.timezone.utc)  # Monday
    assert next_optimal_publish_time(now) == "2026-07-15T17:00:00Z"


def test_same_day_if_still_enough_lead_time():
    now = dt.datetime(2026, 7, 15, 10, 0, tzinfo=dt.timezone.utc)  # Wednesday morning
    assert next_optimal_publish_time(now) == "2026-07-15T17:00:00Z"


def test_skips_to_next_slot_if_too_close():
    now = dt.datetime(2026, 7, 15, 16, 30, tzinfo=dt.timezone.utc)  # Wednesday, <2h before 17:00
    assert next_optimal_publish_time(now) == "2026-07-16T17:00:00Z"


def test_wraps_to_next_week_after_both_slots_pass():
    now = dt.datetime(2026, 7, 16, 20, 0, tzinfo=dt.timezone.utc)  # Thursday evening
    assert next_optimal_publish_time(now) == "2026-07-22T17:00:00Z"
