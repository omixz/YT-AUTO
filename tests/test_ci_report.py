import json
import os
import time

import ci_report

PASSED = {"title": "T", "format": "longform", "niche": "n", "topic": "x",
          "passed_quality_gate": True, "youtube_video_id": "abc",
          "youtube_url": "https://youtu.be/abc", "privacy_status": "public"}
FAILED = {**PASSED, "passed_quality_gate": False, "privacy_status": "private",
          "quality_gate_reasons": ["too short"]}


def test_needs_review_only_for_real_gate_failures():
    assert ci_report.needs_review(FAILED)
    assert not ci_report.needs_review(PASSED)
    assert not ci_report.needs_review({**FAILED, "youtube_video_id": None})  # dry run
    assert not ci_report.needs_review({"passed_quality_gate": False})        # no upload


def test_summary_lists_reasons_and_link():
    s = ci_report.build_summary(FAILED)
    assert "FAILED" in s and "too short" in s and "https://youtu.be/abc" in s


def test_latest_manifest_picks_newest(tmp_path):
    for name, title in (("old", "A"), ("new", "B")):
        d = tmp_path / name
        d.mkdir()
        (d / "manifest.json").write_text(json.dumps({"title": title}))
        os.utime(d / "manifest.json", (time.time() - (100 if name == "old" else 0),) * 2)
    assert ci_report.latest_manifest(tmp_path)["title"] == "B"
    assert ci_report.latest_manifest(tmp_path / "missing") is None


def test_output_value_cannot_inject_extra_outputs(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    ci_report._set_output("title", "x\nneeds_review=true")
    assert out.read_text().count("\n") == 1
