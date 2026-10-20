import datetime as dt

from youtube_automation import growth_ledger as gl


def test_private_and_gate_failed_are_not_scorable():
    assert gl.is_scorable({"privacy_status": "public", "passed_quality_gate": True})
    assert not gl.is_scorable({"privacy_status": "private", "passed_quality_gate": False})
    assert not gl.is_scorable({"privacy_status": "public", "passed_quality_gate": False})
    assert gl.is_scorable({"privacy_status": "public"})            # old records without the field stay scorable


def test_repair_removes_only_zeros_owed_by_private_videos():
    today = dt.date(2026, 10, 20)
    stats = {"mythology:longform": {"samples": 4, "total_score": 60.0, "avg_score": 15.0, "history": [
        {"date": "2026-10-10", "score": 0.0}, {"date": "2026-10-10", "score": 0.0},
        {"date": "2026-10-11", "score": 30.0}, {"date": "2026-10-12", "score": 30.0}]}}
    records = [{"niche": "mythology", "format": "longform", "scored": True, "privacy_status": "private", "passed_quality_gate": False},
               {"niche": "mythology", "format": "longform", "scored": True, "privacy_status": "public", "passed_quality_gate": True}]
    out = gl.repair_stats(stats, records, today)["mythology:longform"]
    assert out["samples"] == 3 and out["avg_score"] == 20.0         # one zero removed, not both
    assert [h["score"] for h in out["history"]] == [0.0, 30.0, 30.0]
