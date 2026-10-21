import datetime as dt

from youtube_automation import growth_ledger as gl


def _rec(**kw):
    base = {"video_id": "v", "niche": "mythology", "format": "longform", "title": "A 1912 Mystery?", "privacy_status": "public",
            "passed_quality_gate": True, "published_at": "2026-09-01", "ctr": 0.04, "impressions": 1000,
            "render": {"thumbnail": {"style": "toon"}}}
    base.update(kw)
    return base


def test_ctr_insights_weights_by_impressions_and_slices_by_style_and_title_shape():
    recs = [_rec(video_id="a", ctr=0.10, impressions=100), _rec(video_id="b", ctr=0.02, impressions=900, title="Plain Title"),
            _rec(video_id="c", ctr=0.05, impressions=500, render={}, niche="world_wars"), _rec(video_id="d", ctr=None)]
    out = gl.ctr_insights(recs)
    assert out["videos_with_ctr"] == 3
    assert out["by_niche"]["mythology"]["ctr"] == round((0.10 * 100 + 0.02 * 900) / 1000, 4)
    assert set(out["by_thumbnail_style"]) == {"toon", "legacy"}
    assert out["by_title_is_question"]["question"]["videos"] == 2 and out["by_title_has_year"]["no_year"]["videos"] == 1


def test_needs_ctr_only_returns_public_mature_unchecked(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    monkeypatch.setattr(gl, "ROOT", tmp_path)
    old = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    recs = [_rec(video_id="ok", published_at=old), _rec(video_id="private", published_at=old, privacy_status="private"),
            _rec(video_id="checked", published_at=old, ctr_checked="2026-10-01"), _rec(video_id="young", published_at=dt.date.today().isoformat())]
    p = tmp_path / gl.LEDGER_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(recs))
    cfg = SimpleNamespace(growth=SimpleNamespace(maturity_days=7))
    assert [r["video_id"] for r in gl.needs_ctr(cfg)] == ["ok"]
