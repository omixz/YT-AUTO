import datetime as dt
import json

from youtube_automation import growth_ledger as gl
from youtube_automation.quality_check import hook_warnings, pick_best_title, title_score
from youtube_automation.script_writer import Scene, Script


def _script(hook="Three men vanished from a locked island in 1900.", title="T", options=()):
    return Script(topic="t", title=title, description="d", tags=[], scenes=[Scene(hook, ["x"], "hook")], title_options=list(options))


def test_hook_warnings_flag_throat_clearing_and_vagueness():
    assert hook_warnings(_script()) == []
    assert "throat-clearing" in hook_warnings(_script("In 1900, three men vanished from an island and nobody knew why."))[0]
    assert any("names nothing specific" in w for w in hook_warnings(_script("it was a strange and quiet night for them all.")))
    assert any("words" in w for w in hook_warnings(_script("Three men vanished " + "and then more happened " * 8)))


def test_best_title_prefers_specific_curious_titles_and_never_overclaims():
    bland = "A Story About Some Old Events"
    good = "Three Keepers Vanished From Flannan Isles: Why?"
    bad = "The Sighting That Proves She Was Trafficked"
    assert title_score(good) > title_score(bland)
    assert pick_best_title(_script(title=bland, options=[good, bad])) == good
    assert pick_best_title(_script(title="Exact Same Quality 1912", options=[])) == "Exact Same Quality 1912"


def test_daily_cap_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(gl, "ROOT", tmp_path)
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    recs = [{"format": "shorts", "published_at": today, "privacy_status": "public", "passed_quality_gate": True},
            {"format": "longform", "published_at": today, "privacy_status": "private", "passed_quality_gate": False},
            {"format": "longform", "published_at": "2026-01-01", "privacy_status": "public", "passed_quality_gate": True}]
    p = tmp_path / gl.LEDGER_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(recs))
    assert gl.daily_counts("shorts") == (1, 1)         # a public Short today -> the next Short run is skipped
    assert gl.daily_counts("longform") == (0, 1)       # only a private failure today -> one retry is allowed


def test_music_is_quieter_than_before():
    # The setting is now actually applied in the mix (it used to be ignored, so music played at 0 dB).
    from youtube_automation.assembler import _build_mix_command
    from youtube_automation.config import PipelineConfig
    db = PipelineConfig.load("config/channel.yaml").video.music_volume_db
    assert -16 <= db <= -6
    from pathlib import Path
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        m = Path(d) / "m.wav"
        m.write_bytes(b"x")
        cmd = _build_mix_command(Path("v.mp4"), Path("n.mp3"), m, None, None, Path("o.mp4"), music_db=db)
    assert f"volume={db:.1f}dB" in " ".join(cmd)
