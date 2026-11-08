import datetime as dt
import random

import pytest

from youtube_automation import branding, crosspost, growth_ledger, niche_selector, pipeline, quality_check, script_writer
from youtube_automation.config import PipelineConfig
from youtube_automation.script_writer import Scene, Script

TODAY = dt.date(2026, 11, 7)
NOW = dt.datetime(2026, 11, 7, 17, 0, tzinfo=dt.timezone.utc)


def _cfg():
    return PipelineConfig.load("config/channel.yaml")


def _rec(vid, fmt="longform", days_ago=1, privacy="public", gate=True, **extra):
    return {"video_id": vid, "niche": "mythology", "format": fmt, "title": f"Title {vid}", "topic": f"Topic {vid}",
            "published_at": (TODAY - dt.timedelta(days=days_ago)).isoformat(), "scored": False,
            "privacy_status": privacy, "passed_quality_gate": gate, **extra}


@pytest.fixture
def ledger(monkeypatch):
    box = {"records": []}
    monkeypatch.setattr(growth_ledger, "_load", lambda path: box["records"])
    monkeypatch.setattr(growth_ledger, "_save", lambda path, recs: box.__setitem__("records", recs))
    return box


# ---- config / format plumbing ----

def test_teaser_is_vertical_and_never_bandit_picked():
    cfg = _cfg()
    assert cfg.video.formats["teaser"].weight == 0
    cfg.video.format = "teaser"
    assert cfg.video.resolution == tuple(cfg.video.resolution_shorts)
    random.seed(3)
    assert {niche_selector.choose(cfg)[1] for _ in range(300)} == {"longform"}


def test_select_forces_teaser_and_keeps_the_promoted_longforms_niche():
    cfg = _cfg()
    niche, fmt = pipeline._select_niche_and_format(cfg, "teaser", niche_key="mythology")
    assert (niche, fmt) == ("mythology", "teaser")
    assert cfg.video.format == "teaser" and cfg.visuals.orientation == "portrait"
    assert cfg.video.target_seconds == cfg.video.formats["teaser"].target_seconds


def test_existing_formats_still_select_normally():
    cfg = _cfg()
    _, fmt = pipeline._select_niche_and_format(cfg, "shorts")
    assert fmt == "shorts" and cfg.visuals.orientation == "portrait"
    _, fmt = pipeline._select_niche_and_format(cfg, "longform")
    assert fmt == "longform" and cfg.visuals.orientation == "landscape"


# ---- which longform gets promoted ----

def test_picks_newest_public_longform_without_a_teaser(ledger):
    ledger["records"] = [_rec("old", days_ago=5), _rec("new", days_ago=1), _rec("short", fmt="shorts", days_ago=0)]
    assert growth_ledger.pick_teaser_source(14, now=NOW)["video_id"] == "new"


def test_already_teased_longform_is_skipped_but_private_teaser_does_not_count(ledger):
    ledger["records"] = [_rec("a", days_ago=1), _rec("b", days_ago=2),
                         _rec("t1", fmt="teaser", teaser_for="a")]
    assert growth_ledger.pick_teaser_source(14, now=NOW)["video_id"] == "b"
    ledger["records"].append(_rec("t2", fmt="teaser", teaser_for="b", privacy="private", gate=False))
    assert growth_ledger.pick_teaser_source(14, now=NOW)["video_id"] == "b"   # failed teaser -> retry allowed


def test_ignores_private_gate_failed_and_out_of_window_longforms(ledger):
    ledger["records"] = [_rec("priv", privacy="private"), _rec("bad", gate=False), _rec("ancient", days_ago=40)]
    assert growth_ledger.pick_teaser_source(14, now=NOW) is None


def test_teaser_has_its_own_daily_cap_bucket(ledger):
    today = dt.datetime.now(dt.timezone.utc).date()
    ledger["records"] = [{**_rec("s1", fmt="shorts", days_ago=0), "published_at": today.isoformat()}]
    assert growth_ledger.daily_counts("teaser") == (0, 0)     # a daily Short does NOT use up the teaser slot
    assert growth_ledger.daily_counts("shorts") == (1, 1)
    ledger["records"].append({**_rec("t1", fmt="teaser"), "published_at": today.isoformat()})
    assert growth_ledger.daily_counts("teaser") == (1, 1)
    assert growth_ledger.daily_counts("shorts") == (1, 1)     # and vice versa


def test_record_published_stores_seed_and_teaser_link(ledger):
    growth_ledger.record_published("mythology", "teaser", "vid", title="t", teaser_for="longform1", seed="")
    growth_ledger.record_published("mythology", "longform", "lf", title="t", seed="opening words")
    t, lf = ledger["records"]
    assert t["teaser_for"] == "longform1" and "seed" not in t
    assert lf["seed"] == "opening words" and "teaser_for" not in lf


# ---- run() skip paths cost nothing ----

def test_run_skips_cleanly_when_nothing_to_tease(ledger, monkeypatch):
    called = []
    monkeypatch.setattr(pipeline, "generate_script", lambda *a, **k: called.append(1))
    out = pipeline.run(_cfg(), format_override="teaser")
    assert out == {"skipped": "no_longform_to_tease", "format": "teaser"} and not called


def test_run_respects_the_teaser_daily_cap(ledger, monkeypatch):
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    ledger["records"] = [{**_rec("t1", fmt="teaser", teaser_for="x"), "published_at": today}]
    monkeypatch.setattr(pipeline, "generate_script", lambda *a, **k: pytest.fail("must not generate"))
    assert pipeline.run(_cfg(), format_override="teaser")["skipped"] == "daily_cap"


# ---- script / CTA / end card ----

def _script(last):
    return Script("t", "A Title", "d " * 10, ["a", "b", "c"],
                  [Scene("Hook sentence here now.", ["x"], "hook"), Scene(last, ["y"], "insight")])


def test_cta_is_appended_only_when_missing():
    s = _script("And then they opened the door.")
    assert quality_check.ensure_teaser_cta(s, "Watch the full story on this channel.")
    assert s.scenes[-1].narration.endswith("Watch the full story on this channel.")
    s2 = _script("Nobody knew. The full story is on my channel.")
    assert not quality_check.ensure_teaser_cta(s2, "X")


def test_teaser_prompt_demands_a_cliffhanger_and_includes_the_source(monkeypatch):
    cfg = _cfg()
    cfg.video.format, cfg.video.target_seconds = "teaser", 40
    seen = {}

    def fake(prompt, name, schema, config, max_tokens):
        seen.setdefault("prompt", prompt)   # the writing prompt; a later tighten pass must not overwrite it
        return {"title": "T", "description": "d", "tags": ["a"], "scenes": [{"role": "hook", "narration": "w " * 200, "visual_keywords": ["k"]}]}

    monkeypatch.setattr(script_writer, "_call_gemini", fake)
    monkeypatch.setattr(script_writer, "_extend_to_length", lambda data, *a, **k: data)
    script_writer.generate_script("Alcatraz", cfg, source={"title": "The Alcatraz Escape", "seed": "In 1962 three men vanished."})
    p = seen["prompt"]
    assert "CLIFFHANGER TEASER RULES" in p and "FORMAT OVERRIDE" in p
    assert "The Alcatraz Escape" in p and "In 1962 three men vanished." in p
    assert "loop back to the first line" in p   # explicitly told NOT to (the daily-Shorts replay rule must not leak in)


def test_daily_shorts_prompt_is_unchanged_by_teaser_support(monkeypatch):
    cfg = _cfg()
    cfg.video.format, cfg.video.target_seconds = "shorts", 40
    seen = {}
    monkeypatch.setattr(script_writer, "_call_gemini", lambda prompt, *a, **k: seen.setdefault("p", prompt) and {"title": "T", "description": "d", "tags": ["a"], "scenes": [{"role": "hook", "narration": "w " * 200, "visual_keywords": ["k"]}]})
    script_writer.generate_script("x", cfg)
    assert "SHORTS RULES" in seen["p"] and "TEASER" not in seen["p"] and "Follow for the full story" in seen["p"]


def test_outro_card_can_point_at_the_longform(tmp_path):
    cfg = _cfg()
    cfg.video.format = "teaser"
    vis, audio = branding.build_outro(cfg, tmp_path, duration=2.5, heading="Full story", cta="The Alcatraz Escape")
    assert vis.path.exists() and audio.duration == 2.5


# ---- cross-post ----

def test_teasers_are_cross_posted_to_tiktok(monkeypatch):
    cfg = _cfg()
    cfg.secrets.buffer_api_key, cfg.secrets.buffer_tiktok_channel_id = "k", "c"
    monkeypatch.setattr(crosspost.media_host, "upload_public", lambda *a, **k: "https://x/y.mp4")
    got = {}
    monkeypatch.setattr(crosspost.buffer_publisher, "publish_tiktok", lambda url, cap, c, title=None: got.setdefault("cap", cap) and "post1")
    monkeypatch.setattr(crosspost, "_channel_name", lambda v: None)
    kw = dict(privacy="public", passed_gate=True, dry_run=False, video_path="v.mp4", run_id="r", title="T", search_phrase="The Alcatraz Escape")
    assert crosspost.tiktok(cfg, format_name="teaser", **kw) == "post1"
    assert "The Alcatraz Escape" in got["cap"]
    assert crosspost.tiktok(cfg, format_name="longform", **kw) is None
