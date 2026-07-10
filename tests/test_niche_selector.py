import json

from youtube_automation import niche_selector
from youtube_automation.config import FormatConfig, GrowthConfig, NicheConfig


def _config(tmp_path, niches, formats, epsilon=0.2, min_samples_for_trust=3):
    growth = GrowthConfig(
        stats_file="stats.json", epsilon=epsilon, min_samples_for_trust=min_samples_for_trust
    )
    video = type("V", (), {"formats": formats})()
    return type("Cfg", (), {"niches": niches, "video": video, "growth": growth})()


def test_cold_start_never_picks_a_disabled_format(tmp_path, monkeypatch):
    monkeypatch.setattr(niche_selector, "ROOT", tmp_path)
    niches = [NicheConfig(key="a", niche="A stuff")]
    formats = {
        "shorts": FormatConfig(enabled=True, weight=1.0),
        "longform": FormatConfig(enabled=False, weight=1.0),
    }
    config = _config(tmp_path, niches, formats)

    for _ in range(20):
        niche_key, format_name = niche_selector.choose(config)
        assert niche_key == "a"
        assert format_name == "shorts"


def test_exploits_best_scoring_combo_once_trusted(tmp_path, monkeypatch):
    monkeypatch.setattr(niche_selector, "ROOT", tmp_path)
    niches = [NicheConfig(key="good", niche="good niche"), NicheConfig(key="bad", niche="bad niche")]
    formats = {"shorts": FormatConfig(enabled=True, weight=1.0)}
    config = _config(tmp_path, niches, formats, epsilon=0.0, min_samples_for_trust=3)

    stats = {
        "good:shorts": {"samples": 5, "avg_score": 100.0},
        "bad:shorts": {"samples": 5, "avg_score": 1.0},
    }
    (tmp_path / "stats.json").write_text(json.dumps(stats), encoding="utf-8")

    for _ in range(10):
        niche_key, format_name = niche_selector.choose(config)
        assert niche_key == "good"


def test_explores_when_not_enough_samples_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(niche_selector, "ROOT", tmp_path)
    niches = [NicheConfig(key="good", niche="good niche"), NicheConfig(key="bad", niche="bad niche")]
    formats = {"shorts": FormatConfig(enabled=True, weight=1.0)}
    config = _config(tmp_path, niches, formats, epsilon=0.2, min_samples_for_trust=3)

    stats = {
        "good:shorts": {"samples": 1, "avg_score": 100.0},
        "bad:shorts": {"samples": 0, "avg_score": 0.0},
    }
    (tmp_path / "stats.json").write_text(json.dumps(stats), encoding="utf-8")

    seen = {niche_selector.choose(config)[0] for _ in range(50)}
    assert seen == {"good", "bad"}, "both combos should get picked while under the trust threshold"


def test_raises_with_no_enabled_combos(tmp_path, monkeypatch):
    monkeypatch.setattr(niche_selector, "ROOT", tmp_path)
    niches = [NicheConfig(key="a", niche="A stuff")]
    formats = {"shorts": FormatConfig(enabled=False)}
    config = _config(tmp_path, niches, formats)

    try:
        niche_selector.choose(config)
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
