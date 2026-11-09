"""The ~2s 'Before we continue, like and subscribe.' beat right after the hook (longform)."""
from youtube_automation.config import PipelineConfig
from youtube_automation.script_writer import Scene, Script, insert_cta_break
from youtube_automation.toon import direction

TEXT = "Before we continue, like and subscribe."


def _script(n=4):
    scenes = [Scene("A man vanished in 1971.", ["plane"], "hook", setting="harbor", time_of_day="night", on_screen=["Cooper"], prop="bag")]
    scenes += [Scene(f"Story beat number {i} about the case.", ["x"], "build") for i in range(n - 2)]
    scenes += [Scene("Why it still matters.", ["x"], "insight")]
    return Script(topic="t", title="T", description="d", tags=[], scenes=scenes)


def test_break_goes_right_after_the_hook_and_copies_its_picture():
    s = _script()
    assert insert_cta_break(s, TEXT)
    b = s.scenes[1]
    assert (b.kind, b.role, b.narration) == ("cta_break", "build", TEXT)
    assert (b.setting, b.time_of_day, b.on_screen, b.action, b.prop) == ("harbor", "night", ["Cooper"], "talk", "bag")
    assert s.scenes[0].role == "hook" and s.scenes[2].narration.startswith("Story beat")
    assert len(s.scenes) == 5


def test_break_is_inserted_once_and_never_into_tiny_or_hookless_scripts():
    s = _script()
    assert insert_cta_break(s, TEXT) and not insert_cta_break(s, TEXT)
    assert sum(x.kind == "cta_break" for x in s.scenes) == 1
    assert not insert_cta_break(Script("t", "T", "d", [], [Scene("a", ["x"], "hook"), Scene("b", ["x"], "insight")]), TEXT)
    no_hook = _script(); no_hook.scenes[0].role = "build"
    assert not insert_cta_break(no_hook, TEXT)
    assert not insert_cta_break(_script(), "  ")


def test_every_format_enables_the_break():
    f = PipelineConfig.load().video.formats
    assert f["longform"].cta_break and f["shorts"].cta_break and f["teaser"].cta_break
    assert PipelineConfig.load().video.cta_break_text == TEXT


def test_break_scene_shows_the_card_from_the_start_and_there_is_no_second_early_card():
    s = _script(8)
    insert_cta_break(s, TEXT)
    d = direction.direct(s.scenes, [6.0, 2.3] + [6.0] * 7, "T")
    assert (d[1].cta, d[1].cta_t) == ("early", 0.15)
    assert [x.cta for x in d].count("early") == 1
    assert d[-1].cta == "final"          # the end-of-video card must survive


def test_without_a_break_the_usual_early_card_is_unchanged():
    s = _script(8)
    d = direction.direct(s.scenes, [6.0] * 8, "T")
    assert [x.cta for x in d].count("early") == 1 and d[-1].cta == "final" and d[1].cta == "early"


def test_teaser_seed_never_contains_the_break(monkeypatch):
    """The ledger stores the longform's opening so the teaser Short retells the SAME story - not the CTA."""
    import inspect
    from youtube_automation import pipeline
    src = inspect.getsource(pipeline.run)
    assert 'sc.kind != "cta_break"' in src and "seed=" in src
