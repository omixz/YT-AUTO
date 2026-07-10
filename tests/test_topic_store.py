import json

from youtube_automation import topic_store


def test_next_topic_override_skips_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(topic_store, "ROOT", tmp_path)
    config = type("Cfg", (), {"topics": type("T", (), {"queue_file": "{niche}/q.yaml", "history_file": "{niche}/h.json"})()})()

    topic = topic_store.next_topic(config, "science_history", override="my custom topic")
    assert topic == "my custom topic"
    # override should not touch the queue/history files
    assert not (tmp_path / "science_history" / "q.yaml").exists()
    assert not (tmp_path / "science_history" / "h.json").exists()


def test_next_topic_pops_queue_and_records_history(tmp_path, monkeypatch):
    monkeypatch.setattr(topic_store, "ROOT", tmp_path)
    queue_path = tmp_path / "science_history" / "q.yaml"
    queue_path.parent.mkdir(parents=True)
    queue_path.write_text("topics:\n  - first\n  - second\n", encoding="utf-8")

    config = type("Cfg", (), {"topics": type("T", (), {"queue_file": "{niche}/q.yaml", "history_file": "{niche}/h.json"})()})()

    topic = topic_store.next_topic(config, "science_history")
    assert topic == "first"

    remaining = queue_path.read_text(encoding="utf-8")
    assert "second" in remaining
    assert "first" not in remaining

    history_path = tmp_path / "science_history" / "h.json"
    history = json.loads(history_path.read_text(encoding="utf-8"))
    assert history == ["first"]


def test_next_topic_keeps_niches_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(topic_store, "ROOT", tmp_path)
    for niche in ("science_history", "unsolved_mysteries"):
        p = tmp_path / niche / "q.yaml"
        p.parent.mkdir(parents=True)
        p.write_text(f"topics:\n  - {niche}-topic-a\n  - {niche}-topic-b\n", encoding="utf-8")

    config = type("Cfg", (), {"topics": type("T", (), {"queue_file": "{niche}/q.yaml", "history_file": "{niche}/h.json"})()})()

    assert topic_store.next_topic(config, "science_history") == "science_history-topic-a"
    assert topic_store.next_topic(config, "unsolved_mysteries") == "unsolved_mysteries-topic-a"
    # each niche's queue advances independently
    assert topic_store.next_topic(config, "science_history") == "science_history-topic-b"
