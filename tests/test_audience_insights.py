import datetime as dt
import json
from types import SimpleNamespace

from youtube_automation import growth_ledger as gl


def _rec(**kw):
    base = {"video_id": "v", "niche": "mythology", "format": "longform", "title": "A 1912 Mystery?", "privacy_status": "public",
            "passed_quality_gate": True, "published_at": "2026-09-01", "views": 100, "avg_view_pct": 30.0, "render": {"thumbnail": {"style": "toon"}}}
    base.update(kw)
    return base


def test_audience_insights_slice_by_style_and_title_shape():
    recs = [_rec(video_id="a", views=300, avg_view_pct=40.0), _rec(video_id="b", views=100, avg_view_pct=20.0, title="Plain Title", render={}),
            {k: v for k, v in _rec(video_id="c").items() if k != "avg_view_pct"}]
    out = gl.audience_insights(recs)
    assert out["videos"] == 2 and out["overall"] == {"avg_views": 200.0, "avg_view_pct": 30.0}
    assert out["by_thumbnail_style"]["toon"]["avg_views"] == 300.0 and out["by_thumbnail_style"]["legacy"]["videos"] == 1
    assert out["by_title_is_question"]["question"]["videos"] == 1 and out["by_title_has_year"]["no_year"]["videos"] == 1


def test_needs_audience_returns_public_mature_without_data(tmp_path, monkeypatch):
    monkeypatch.setattr(gl, "ROOT", tmp_path)
    old = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    nodata = {k: v for k, v in _rec(video_id="ok", published_at=old).items() if k not in ("avg_view_pct", "views")}
    recs = [nodata, _rec(video_id="private", published_at=old, privacy_status="private"), _rec(video_id="done", published_at=old),
            {**nodata, "video_id": "young", "published_at": dt.date.today().isoformat()}]
    p = tmp_path / gl.LEDGER_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(recs))
    assert [r["video_id"] for r in gl.needs_audience(SimpleNamespace(growth=SimpleNamespace(maturity_days=7)))] == ["ok"]
