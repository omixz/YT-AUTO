import pytest


@pytest.fixture(autouse=True)
def _no_network_for_topic_demand(monkeypatch):
    """Topic demand ranking calls Wikipedia; tests stay offline unless they inject their own fetcher."""
    from youtube_automation import topic_demand
    monkeypatch.setattr(topic_demand, "fetch_avg_daily_views", lambda topic, days=60: None)
    monkeypatch.setattr(topic_demand.demand_factors, "__defaults__", (lambda topic: None,))
