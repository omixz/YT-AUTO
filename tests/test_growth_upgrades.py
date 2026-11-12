"""Viral/monetization upgrades: per-format daily caps, discovery hashtags, learning from winning titles."""
import json

from youtube_automation import growth_ledger, pipeline, script_writer
from youtube_automation.config import PipelineConfig


def test_one_short_and_one_longform_a_day():
    cfg = PipelineConfig.load()
    assert cfg.video.formats["shorts"].daily_cap == 1
    assert not pipeline._over_daily_cap(cfg, "shorts", 0, 1)
    assert pipeline._over_daily_cap(cfg, "shorts", 1, 1)
    assert pipeline._over_daily_cap(cfg, "shorts", 0, 2)      # attempts cap = daily_cap + 1
    assert pipeline._over_daily_cap(cfg, "longform", 1, 1)
    assert not pipeline._over_daily_cap(cfg, "longform", 0, 1)  # one retry after a gate-failed private upload


def test_longform_stays_long_enough_for_midroll_ads():
    assert PipelineConfig.load().video.formats["longform"].target_seconds >= 8 * 60


def test_discovery_hashtags():
    assert pipeline.discovery_hashtags("world_wars", "shorts") == "#Shorts #WorldWars #History"
    assert pipeline.discovery_hashtags("unsolved_mysteries", "longform") == "#UnsolvedMysteries #History #Documentary"


def test_winning_titles_are_fed_into_the_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(growth_ledger, "ROOT", tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / growth_ledger.LEDGER_PATH).write_text(json.dumps([
        {"video_id": "a", "format": "shorts", "title": "Big Winner", "views": 314, "privacy_status": "public"},
        {"video_id": "b", "format": "shorts", "title": "Tiny", "views": 3, "privacy_status": "public"},
        {"video_id": "c", "format": "longform", "title": "Long One", "views": 90, "privacy_status": "public"},
        {"video_id": "d", "format": "shorts", "title": "Private Hit", "views": 999, "privacy_status": "private"},
    ]))
    block = script_writer._winning_titles_block("shorts")
    assert "Big Winner" in block and "Tiny" not in block and "Long One" not in block and "Private Hit" not in block
    assert "Long One" in script_writer._winning_titles_block("longform")


def test_no_winning_titles_block_without_data(tmp_path, monkeypatch):
    monkeypatch.setattr(growth_ledger, "ROOT", tmp_path)
    assert script_writer._winning_titles_block("shorts") == ""
