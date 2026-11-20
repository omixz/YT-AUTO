"""Copy what already works on this channel: person-led titles, no year-led titles, no Shorts lost to the gate, no noisy trend."""
from youtube_automation import niche_selector
from youtube_automation.config import PipelineConfig
from youtube_automation.quality_check import title_score


def test_person_led_titles_beat_year_led_titles():
    winners = ["The 18-Year-Old Farm Girl Who Accidentally Started WWI",            # 950 views
               "The Man Who Parachuted Into a Storm With $200,000 and Disappeared"]  # 292 views
    losers = ["The 1930 St Kilda Evacuation: Why Did They Leave Everything Set?",    # 4 views
              "The 1900 Eilean Mor Lighthouse Disappearance Mystery"]                # 4 views
    assert min(map(title_score, winners)) > max(map(title_score, losers))


def test_tightened_shorts_clear_the_gate():
    q = PipelineConfig.load().quality
    assert q.min_words <= 80 and q.min_scenes <= 5   # what _tighten_short produces on purpose


def _stats(dates, scores):
    hist = [{"date": d, "score": s} for d, s in zip(dates, scores)]
    return {"x:shorts": {"samples": len(hist), "avg_score": 100, "history": hist,
                         "windows": {"7d": {"avg_score": 10}, "30d": {"avg_score": 100}}}}


def test_one_weak_recent_video_is_not_a_trend():
    st = _stats(["2026-10-01", "2026-10-05", "2026-10-09", "2026-10-20", "2026-11-14"], [100] * 4 + [10])
    assert niche_selector._trend_score(st, "x", "shorts") == 0.0


def test_a_real_recent_window_still_counts():
    st = _stats(["2026-10-01", "2026-10-05", "2026-11-12", "2026-11-13", "2026-11-14"], [100, 100, 10, 10, 10])
    assert niche_selector._trend_score(st, "x", "shorts") < 0


def test_an_empty_recent_window_is_not_a_crash():
    st = _stats(["2026-10-01", "2026-10-05", "2026-10-09", "2026-10-11", "2026-10-12"], [100] * 5)
    st["x:shorts"]["windows"]["7d"] = {}
    assert niche_selector._trend_score(st, "x", "shorts") == 0.0
