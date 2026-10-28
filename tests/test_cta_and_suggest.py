from pathlib import Path

from youtube_automation import crosspost, youtube_suggest
from youtube_automation.script_writer import Scene
from youtube_automation.toon import direction, engine


def test_top_query_picks_the_first_matching_suggestion():
    sug = {"flannan isles lighthouse keepers": ["flannan isles lighthouse mystery", "flannan isles lighthouse keepers"], "flannan isles": ["flannan isles"]}
    got = youtube_suggest.top_query("The 1912 Flannan Isles Lighthouse Keepers Mystery", fetch=lambda q: sug.get(q.lower(), []))
    assert got == "flannan isles lighthouse mystery"


def test_top_query_ignores_unrelated_suggestions_and_survives_errors():
    assert youtube_suggest.top_query("The Flannan Isles Mystery", fetch=lambda q: ["minecraft house", "cat videos"]) is None
    assert youtube_suggest.top_query("The Flannan Isles Mystery", fetch=lambda q: (_ for _ in ()).throw(OSError("down"))) is None


def test_tiktok_caption_markets_youtube_with_the_exact_search_phrase():
    c = crosspost.build_caption("Title", "flannan isles mystery", "History Chan", "#fyp")
    assert "search \"flannan isles mystery\"" in c and "History Chan" in c and "Like" in c and "Subscribe" in c and c.endswith("#fyp")
    assert "link in bio" in crosspost.build_caption("T", None, None, "#x")


def test_cta_placement():
    long = direction.direct([Scene(f"Scene {i} about 1912.", ["x"], "build") for i in range(20)], [4.0] * 20, "T")
    assert [d.cta for d in long].count("mid") == 1 and long[-1].cta == "final" and long[int(20 * 0.4)].cta == "mid"
    short = direction.direct([Scene(f"Scene {i} here.", ["x"], "build") for i in range(6)], [4.0] * 6, "T")
    assert [d.cta for d in short] == ["", "", "", "", "", "final"]


def test_cta_card_changes_the_frame(tmp_path):
    base = direction.direct([Scene("A scene.", ["x"], "build")], [4.0], "T")[0]
    base = base.__class__(**{**base.__dict__, "cta": ""})
    with_cta = base.__class__(**{**base.__dict__, "cta": "mid"})
    frames = []
    for name, d in (("a", base), ("b", with_cta)):
        engine.render_scene(d, 2.0, 320, 180, 10, tmp_path / f"{name}.mp4", dump_frames=[1.5], frames_dir=tmp_path)
        frames.append((tmp_path / f"{name}_1.5.png").read_bytes())
    assert frames[0] != frames[1]
