"""Roblox story Shorts: captions, procedural background, routing and safety rules."""
import re

import roblox_stories as R
from youtube_automation.stories import captions, obby


def test_caption_events_never_overlap_and_cover_every_word():
    words = [(i * 0.3, i * 0.3 + 0.25, w) for i, w in enumerate("My best friend scammed me. I got it back, though!".split())]
    ass = captions.build_ass(words, "Hook")
    caps = [l for l in ass.splitlines() if l.startswith("Dialogue: 0,")]
    assert len(caps) == len(words)

    def secs(ts):
        h, m, s = ts.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    spans = [(secs(l.split(",")[1]), secs(l.split(",")[2])) for l in caps]
    assert all(a_end <= b_start + 1e-6 for (_, a_end), (b_start, _) in zip(spans, spans[1:]))
    assert "Title" in ass and "scammed" in ass


def test_groups_break_on_punctuation_and_stay_short():
    words = [(0, 0, w) for w in "This is a very long sentence. Short one!".split()]
    groups = captions.group_words(words)
    assert all(len(g) <= 3 for g in groups)
    assert any(g[-1][2].endswith(".") for g in groups)


def test_procedural_obby_renders_frames():
    frames = obby.frames(0.2, 108, 192, 10, seed=1)
    f = next(iter(frames))
    assert f.shape == (192, 108, 4) and f[..., :3].std() > 5   # not a blank frame


def test_player_always_has_a_position_on_the_course():
    plats = obby.build_course(3, 30)
    for t in (0, 1.3, 7.7, 29.0):
        x, y, z, _air, _ph = obby.player_state(plats, t)
        assert -10 < x < 10 and -10 < y < 12 and z >= 0


def test_separate_channel_is_default_and_uses_its_own_token(monkeypatch):
    monkeypatch.delenv("STORIES_TOKEN_FILE", raising=False)
    cfg = R.load_cfg()
    assert cfg["channel"] == "separate"
    assert R.token_path(cfg).name == "stories_token.json"
    assert R.token_path({"channel": "main"}).name == "token.json"


def test_prompt_carries_the_safety_rules_and_avoids_repeats():
    p = R.story_prompt({"min_words": 110, "max_words": 170}, [{"title": "The Admin Who Banned Me"}], "Adopt Me")
    for rule in ("no romance", "no real usernames", "never presented as news"):
        assert rule in p
    assert "The Admin Who Banned Me" in p and "Adopt Me" in p


def test_description_discloses_fiction_and_ai_voice():
    d = R.description_for({"description": "Would you forgive her?"})
    assert re.search(r"fictional story narrated with an AI voice", d)
