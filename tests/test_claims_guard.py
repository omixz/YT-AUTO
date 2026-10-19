import json

from youtube_automation import growth_ledger
from youtube_automation.quality_check import has_unproven_certainty


def test_certainty_titles_are_flagged():
    assert has_unproven_certainty("The Disappearance And The Sighting That Proves She Was Trafficked")
    assert has_unproven_certainty("Exposed: The Real Truth About the Cover-Up")
    assert not has_unproven_certainty("The Disappearance of Amy Bradley: What Witnesses Claimed")
    assert not has_unproven_certainty("Why Did the General Disobey Orders?")


def test_ledger_records_render_engines(tmp_path, monkeypatch):
    monkeypatch.setattr(growth_ledger, "ROOT", tmp_path)
    growth_ledger.record_published("n", "longform", "vid1", title="t", render={"animation": {"engine": "toon", "fallback_scenes": 0}})
    rec = json.loads((tmp_path / growth_ledger.LEDGER_PATH).read_text())[-1]
    assert rec["render"]["animation"]["engine"] == "toon"
