import random

from youtube_automation import niche_selector
from youtube_automation.config import PipelineConfig


def _cfg():
    return PipelineConfig.load("config/channel.yaml")


def test_forced_shorts_works_even_though_its_bandit_weight_is_zero():
    cfg = _cfg()
    assert cfg.video.formats["shorts"].weight == 0
    niche, fmt = niche_selector.choose(cfg, format_override="shorts")
    assert fmt == "shorts" and niche


def test_daily_bandit_never_picks_a_weight_zero_format_even_if_it_scores_best(monkeypatch):
    cfg = _cfg()
    stats = {niche_selector.stats_key(n.key, "shorts"): {"samples": 99, "avg_score": 999.0, "history": []} for n in cfg.niches}
    monkeypatch.setattr(niche_selector, "_load_stats", lambda path: stats)
    random.seed(1)
    assert {niche_selector.choose(cfg)[1] for _ in range(300)} == {"longform"}
