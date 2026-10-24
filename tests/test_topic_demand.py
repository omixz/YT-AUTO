from types import SimpleNamespace

from youtube_automation import niche_selector, topic_demand


def test_query_is_short_and_drops_filler():
    q = topic_demand.query_for("The 1912 vanishing of lighthouse keepers on the Flannan Isles, where relief workers arrived to find tables set")
    assert q.split()[:3] == ["1912", "vanishing", "lighthouse"] and len(q.split()) <= 9 and "the" not in q.lower().split()


def test_factors_are_log_scaled_neutral_when_unknown_and_flat_without_data():
    views = {"a": 10000.0, "b": 100.0, "c": None}
    f = topic_demand.demand_factors(list(views), fetch=lambda t: views[t])
    assert f["a"] == 1.0 and 0.6 < f["b"] < f["a"] and f["c"] == 0.8
    assert topic_demand.demand_factors(["x", "y"], fetch=lambda t: None) == {"x": 1.0, "y": 1.0}      # no signal -> no change
    assert topic_demand.demand_factors(["x", "y"], fetch=lambda t: 50.0 if t == "x" else None) == {"x": 1.0, "y": 1.0}   # one data point isn't a comparison


def test_picker_prefers_the_topic_people_actually_look_up(monkeypatch):
    cfg = SimpleNamespace(topics=SimpleNamespace(use_demand_ranking=True))
    monkeypatch.setattr(niche_selector, "_seasonal_multiplier", lambda *a: 1.0)
    monkeypatch.setattr(niche_selector, "_competitor_gap_score", lambda *a: 1.0)
    monkeypatch.setattr(niche_selector, "_topic_freshness", lambda *a: 1.0)
    monkeypatch.setattr(topic_demand, "demand_factors", lambda topics: {"obscure": 0.6, "famous": 1.0})
    assert niche_selector.choose_topic_with_intelligence(cfg, "dark_history", ["obscure", "famous"], []) == "famous"
    monkeypatch.setattr(topic_demand, "demand_factors", lambda topics: (_ for _ in ()).throw(RuntimeError("wikipedia down")))
    assert niche_selector.choose_topic_with_intelligence(cfg, "dark_history", ["obscure", "famous"], []) == "obscure"   # failure -> original order
