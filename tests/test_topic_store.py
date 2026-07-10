import json

from youtube_automation import topic_store


def test_next_topic_override_skips_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(topic_store, "ROOT", tmp_path)
    config = type("Cfg", (), {"topics": type("T", (), {"queue_file": "q.yaml", "history_file": "h.json"})()})()

    topic = topic_store.next_topic(config, override="my custom topic")
    assert topic == "my custom topic"
    # override should not touch the queue/history files
    assert not (tmp_path / "q.yaml").exists()
    assert not (tmp_path / "h.json").exists()


def test_next_topic_pops_queue_and_records_history(tmp_path, monkeypatch):
    monkeypatch.setattr(topic_store, "ROOT", tmp_path)
    (tmp_path / "q.yaml").write_text("topics:\n  - first\n  - second\n", encoding="utf-8")

    config = type("Cfg", (), {"topics": type("T", (), {"queue_file": "q.yaml", "history_file": "h.json"})()})()

    topic = topic_store.next_topic(config)
    assert topic == "first"

    remaining = (tmp_path / "q.yaml").read_text(encoding="utf-8")
    assert "second" in remaining
    assert "first" not in remaining

    history = json.loads((tmp_path / "h.json").read_text(encoding="utf-8"))
    assert history == ["first"]
