from youtube_automation import reporting


_RECORD = {
    "video_id": "abc123def45",
    "niche": "unsolved_mysteries",
    "format": "longform",
    "title": "The Flight That Vanished",
    "published_at": "2026-07-11",
}

_STATS = {
    "views": 120,
    "minutes_watched": 95.0,
    "avg_view_duration_s": 48.0,
    "avg_view_percentage": 21.0,
    "likes": 4,
    "comments": 1,
    "shares": 0,
    "subscribers_gained": 0,
    "traffic_sources": {"BROWSE": 70, "YT_SEARCH": 10, "RELATED_VIDEO": 40},
}


def test_report_includes_every_traffic_source_with_lever():
    md = reporting._render_markdown(_RECORD, _STATS, None, window_days=7)
    assert "Browse / home feed" in md
    assert "YouTube search" in md
    assert "Suggested videos" in md
    # Every listed source row carries an actionable lever, not just a count.
    assert "thumbnail" in md.lower()


def test_low_retention_triggers_hook_recommendation():
    recs = reporting._recommendations(_STATS, None, _RECORD)
    assert any("Retention is low" in r for r in recs)


def test_views_without_subs_triggers_cta_recommendation():
    recs = reporting._recommendations(_STATS, None, _RECORD)
    assert any("zero subscribers" in r for r in recs)


def test_overperformer_vs_channel_average_is_called_out():
    avgs = {"views": 40, "avg_view_percentage": 25.0, "subscribers_gained": 1, "likes": 2}
    recs = reporting._recommendations(_STATS, avgs, _RECORD)
    assert any("beat the channel average" in r for r in recs)


def test_channel_averages_from_history():
    history = [
        {"stats": {"views": 10, "avg_view_percentage": 20.0, "subscribers_gained": 0, "likes": 1}},
        {"stats": {"views": 30, "avg_view_percentage": 40.0, "subscribers_gained": 2, "likes": 3}},
    ]
    avgs = reporting._channel_averages(history)
    assert avgs["views"] == 20
    assert avgs["avg_view_percentage"] == 30.0


def test_missing_title_renders_placeholder():
    record = dict(_RECORD, title=None)
    md = reporting._render_markdown(record, _STATS, None, window_days=7)
    assert "(title not recorded)" in md
