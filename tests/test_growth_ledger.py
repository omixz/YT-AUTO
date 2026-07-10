import datetime as dt
import json

from youtube_automation import growth_ledger
from youtube_automation.config import GrowthConfig


def _config(stats_file="stats.json", maturity_days=7):
    return type("Cfg", (), {"growth": GrowthConfig(stats_file=stats_file, maturity_days=maturity_days)})()


def test_record_published_then_visible_as_unscored(tmp_path, monkeypatch):
    monkeypatch.setattr(growth_ledger, "ROOT", tmp_path)
    growth_ledger.record_published("science_history", "shorts", "vid123")

    ledger_path = tmp_path / growth_ledger.LEDGER_PATH
    records = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert records[0]["video_id"] == "vid123"
    assert records[0]["scored"] is False
    assert records[0]["published_at"] == dt.date.today().isoformat()


def test_only_mature_unscored_records_returned(tmp_path, monkeypatch):
    monkeypatch.setattr(growth_ledger, "ROOT", tmp_path)
    ledger_path = tmp_path / growth_ledger.LEDGER_PATH
    ledger_path.parent.mkdir(parents=True, exist_ok=True)

    today = dt.date.today()
    records = [
        {"video_id": "old_unscored", "niche": "a", "format": "shorts",
         "published_at": (today - dt.timedelta(days=10)).isoformat(), "scored": False},
        {"video_id": "old_scored", "niche": "a", "format": "shorts",
         "published_at": (today - dt.timedelta(days=10)).isoformat(), "scored": True},
        {"video_id": "too_recent", "niche": "a", "format": "shorts",
         "published_at": today.isoformat(), "scored": False},
    ]
    ledger_path.write_text(json.dumps(records), encoding="utf-8")

    mature = growth_ledger.unscored_mature_records(_config(maturity_days=7))
    ids = {r["video_id"] for r in mature}
    assert ids == {"old_unscored"}


def test_mark_scored_flips_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(growth_ledger, "ROOT", tmp_path)
    growth_ledger.record_published("science_history", "shorts", "vid123")
    growth_ledger.mark_scored("vid123")

    records = json.loads((tmp_path / growth_ledger.LEDGER_PATH).read_text(encoding="utf-8"))
    assert records[0]["scored"] is True


def test_apply_score_accumulates_average(tmp_path, monkeypatch):
    monkeypatch.setattr(growth_ledger, "ROOT", tmp_path)
    config = _config()

    growth_ledger.apply_score(config, "science_history", "shorts", 100.0)
    growth_ledger.apply_score(config, "science_history", "shorts", 50.0)

    stats = json.loads((tmp_path / "stats.json").read_text(encoding="utf-8"))
    entry = stats["science_history:shorts"]
    assert entry["samples"] == 2
    assert entry["total_score"] == 150.0
    assert entry["avg_score"] == 75.0
