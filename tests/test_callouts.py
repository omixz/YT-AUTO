import subprocess
from types import SimpleNamespace

from youtube_automation.script_writer import Scene
from youtube_automation.toon import callouts, direction, engine


def _cues(*pairs):
    return [SimpleNamespace(text=t, start=s, end=s + 0.3) for t, s in pairs]


def test_years_and_numbers_with_units_become_cards():
    cues = _cues(("In", 0.3), ("1912,", 0.6), ("a", 1.0), ("crew", 1.2), ("of", 1.5), ("1,500", 4.0), ("men.", 4.4), ("sailed", 5.0))
    assert callouts.extract(cues, 8.0) == [(0.6, "1912"), (4.0, "1,500 MEN")]


def test_cards_respect_spacing_edges_and_limit():
    cues = _cues(("1900", 0.1), ("1901", 0.5), ("1902", 1.0), ("1903", 3.9), ("1904", 7.5), ("1905", 9.0))
    got = callouts.extract(cues, 10.0)
    assert [t for t, _ in got] == [0.5, 3.9] and len(got) <= 2      # skips the first 0.25s, enforces gaps, caps at 2


def test_scene_with_a_callout_renders_a_different_frame(tmp_path):
    base = direction.direct([Scene("In 1912 it happened.", ["x"], "build", action="talk")], [3.0], "T")[0]
    with_card = base.__class__(**{**base.__dict__, "callouts": [(0.3, "1912")]})
    paths = []
    for name, d in (("a", base), ("b", with_card)):
        out = engine.render_scene(d, 1.5, 320, 180, 10, tmp_path / f"{name}.mp4", dump_frames=[1.0], frames_dir=tmp_path)
        paths.append(tmp_path / f"{name}_1.0.png")
    assert paths[0].read_bytes() != paths[1].read_bytes()
