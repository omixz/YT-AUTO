"""Double down on winners: breakout videos get follow-up topics queued first in their niche."""
import json
import logging

import sync_analytics
from youtube_automation import growth_ledger, topic_store
from youtube_automation.config import PipelineConfig


def _cfg():
    return type("Cfg", (), {"topics": type("T", (), {"queue_file": "{niche}/q.yaml", "history_file": "{niche}/h.json"})()})()


def _ledger(tmp_path, monkeypatch, records):
    monkeypatch.setattr(growth_ledger, "ROOT", tmp_path)
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / growth_ledger.LEDGER_PATH).write_text(json.dumps(records))


def test_breakouts_are_judged_against_their_own_format(tmp_path, monkeypatch):
    shorts = [{"video_id": f"s{i}", "format": "shorts", "views": v, "privacy_status": "public"} for i, v in enumerate([10, 20, 25, 950, 18])]
    longs = [{"video_id": f"l{i}", "format": "longform", "views": v, "privacy_status": "public"} for i, v in enumerate([3, 5, 6, 40])]
    done = {"video_id": "s9", "format": "shorts", "views": 900, "privacy_status": "public", "followups_queued": "2026-11-01"}
    private = {"video_id": "p", "format": "shorts", "views": 5000, "privacy_status": "private"}
    _ledger(tmp_path, monkeypatch, shorts + longs + [done, private])
    ids = [r["video_id"] for r in growth_ledger.breakout_videos()]
    assert ids == ["s3"]   # 40-view longform is 8x its median but under the 100-view floor


def test_priority_topics_are_served_first_and_queue_survives(tmp_path, monkeypatch):
    monkeypatch.setattr(topic_store, "ROOT", tmp_path)
    q = tmp_path / "ww" / "q.yaml"
    q.parent.mkdir(parents=True)
    q.write_text("topics:\n  - normal one\n  - normal two\n", encoding="utf-8")
    (tmp_path / "ww" / "h.json").write_text(json.dumps(["Already Done"]))
    assert topic_store.push_priority(_cfg(), "ww", ["Follow A", "already done", "Follow B"]) == 2
    assert topic_store.push_priority(_cfg(), "ww", ["Follow A"]) == 0      # no duplicates
    assert topic_store.next_topic(_cfg(), "ww") == "Follow A"
    assert topic_store.next_topic(_cfg(), "ww") == "Follow B"
    assert topic_store._load_queue(q) == ["normal one", "normal two"]
    assert topic_store.next_topic(_cfg(), "ww") in ("normal one", "normal two")
    assert "Follow A" in json.loads((tmp_path / "ww" / "h.json").read_text())


def test_sync_queues_followups_once_per_breakout(tmp_path, monkeypatch):
    cfg = PipelineConfig.load()
    cfg.secrets.gemini_api_key = "k"
    cfg.topics.queue_file, cfg.topics.history_file = "{niche}/q.yaml", "{niche}/h.json"
    monkeypatch.setattr(topic_store, "ROOT", tmp_path)
    recs = [{"video_id": f"s{i}", "niche": "world_wars", "format": "shorts", "title": f"T{i}", "views": v,
             "privacy_status": "public"} for i, v in enumerate([10, 12, 950])]
    _ledger(tmp_path, monkeypatch, recs)
    calls = []
    monkeypatch.setattr("youtube_automation.script_writer.brainstorm_followups",
                        lambda config, niche, title, views, existing: calls.append(title) or ["Next big one", "Another"])
    sync_analytics._queue_breakout_followups(cfg, logging.getLogger("t"))
    sync_analytics._queue_breakout_followups(cfg, logging.getLogger("t"))   # second sync: nothing new
    assert calls == ["T2"]
    assert topic_store._load_priority(tmp_path / "world_wars" / "q.yaml") == ["Next big one", "Another"]
