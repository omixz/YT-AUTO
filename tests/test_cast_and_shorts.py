import random
import subprocess
from pathlib import Path

from youtube_automation import script_writer as sw
from youtube_automation.config import PipelineConfig
from youtube_automation.script_writer import Scene
from youtube_automation.toon import casting, direction, engine


def test_era_detection():
    mk = lambda t: [Scene(t, ["x"])]
    assert casting.detect_era(mk("In August 1914 the army marched."), "") == "ww1"
    assert casting.detect_era(mk("The 1066 invasion changed England."), "") == "medieval"
    assert casting.detect_era(mk("The Nazi regime fell."), "") == "ww2"
    assert casting.detect_era(mk("She vanished from a cruise ship in 1999."), "") == "modern"


def test_cast_is_diverse_and_not_all_knights():
    rng = random.Random(5)
    looks = [casting.random_look("modern", rng) for _ in range(120)]
    assert {l.female for l in looks} == {True, False}
    assert len({l.hair_style for l in looks}) >= 4 and len({l.style for l in looks}) >= 3
    assert len({l.skin for l in looks}) >= 4 and any(l.glasses for l in looks) and any(l.facial for l in looks)
    assert not any(l.style == "armor" or l.headwear == "helmet" for l in looks)


def test_ww1_soldiers_wear_period_uniforms_not_armour():
    rng = random.Random(9)
    soldiers = [casting.random_look("ww1", rng, military=True, female=False) for _ in range(40)]
    assert all(l.style == "uniform" and l.headwear in {"adrian", "brodie", "pickelhaube", "kepi", "peaked"} for l in soldiers)


def test_heroes_rotate_and_shots_vary():
    scenes = [Scene(f"A scene about 1914 number {i}.", ["x"], "build", action="talk") for i in range(12)]
    d = direction.direct(scenes, [4.0] * 12, "T")
    heroes = [id(x.hero) for x in d]
    assert all(a != b for a, b in zip(heroes, heroes[1:])) and len(set(heroes)) >= 3
    assert {x.shot for x in d} >= {"wide", "medium", "close"} and {x.era for x in d} == {"ww1"}


def test_portrait_short_clip_renders(tmp_path):
    d = direction.direct([Scene("A short hook about 1999.", ["x"], "hook")], [1.0], "T")[0]
    out = engine.render_scene(d, 1.0, 270, 480, 12, tmp_path / "s.mp4")
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True).stdout.strip()
    assert probe == "270,480"


def test_shorts_are_enabled_with_short_scenes():
    cfg = PipelineConfig.load("config/channel.yaml")
    assert cfg.video.formats["shorts"].enabled and cfg.video.formats["shorts"].target_seconds <= 60
    words, scenes, _ = sw._script_length_params(cfg.video.formats["shorts"].target_seconds, cfg.voice.words_per_minute)
    assert scenes >= 8                                   # ~4s scenes keep a Short moving
    assert '0 22 * * *' in Path(".github/workflows/publish.yml").read_text()
