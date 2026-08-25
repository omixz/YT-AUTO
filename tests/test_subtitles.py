from youtube_automation.subtitles import build_ass
from youtube_automation.tts import SceneAudio, WordCue


def _scene(words, duration):
    cues = []
    t = 0.0
    for w in words:
        dur = duration / len(words)
        cues.append(WordCue(text=w, start=t, end=t + dur))
        t += dur
    return SceneAudio(scene_index=0, audio_path=__file__, duration=duration, cues=cues)


def test_ass_has_karaoke_fill_tags(tmp_path):
    scene = _scene(["the", "octopus", "has", "three", "hearts"], 3.0)
    path = build_ass([scene], tmp_path / "captions.ass", resolution=(1920, 1080))
    text = path.read_text()
    assert "\\kf" in text
    assert "Dialogue:" in text
    assert "octopus" in text


def test_ass_declares_play_resolution(tmp_path):
    scene = _scene(["hello", "world"], 1.0)
    path = build_ass([scene], tmp_path / "captions.ass", resolution=(1080, 1920))
    text = path.read_text()
    assert "PlayResX: 1080" in text
    assert "PlayResY: 1920" in text


def test_ass_font_size_scales_with_resolution(tmp_path):
    scene = _scene(["hi"], 1.0)
    small = build_ass([scene], tmp_path / "a.ass", resolution=(640, 360)).read_text()
    big = build_ass([scene], tmp_path / "b.ass", resolution=(1920, 1080)).read_text()

    def fontsize(text):
        line = [l for l in text.splitlines() if l.startswith("Style: Default,")][0]
        return int(line.split(",")[2])

    assert fontsize(big) > fontsize(small)


def test_empty_scene_produces_no_dialogue_lines(tmp_path):
    scene = SceneAudio(scene_index=0, audio_path=__file__, duration=2.0, cues=[])
    path = build_ass([scene], tmp_path / "captions.ass", resolution=(1920, 1080))
    assert "Dialogue:" not in path.read_text()


def test_on_screen_text_renders_as_emphasis_dialogue(tmp_path):
    scene = _scene(["the", "octopus", "has", "three", "hearts"], 3.0)
    path = build_ass(
        [scene], tmp_path / "captions.ass", resolution=(1920, 1080),
        on_screen_texts=["3 hearts"],
    )
    text = path.read_text()
    assert "Style: Emphasis" in text
    assert "Dialogue: 1," in text
    assert "3 HEARTS" in text


def test_blank_on_screen_text_produces_no_emphasis_line(tmp_path):
    scene = _scene(["hello", "world"], 2.0)
    path = build_ass(
        [scene], tmp_path / "captions.ass", resolution=(1920, 1080), on_screen_texts=[""],
    )
    assert "Dialogue: 1," not in path.read_text()


def test_on_screen_text_skipped_on_too_short_a_scene(tmp_path):
    scene = _scene(["hi"], 0.3)
    path = build_ass(
        [scene], tmp_path / "captions.ass", resolution=(1920, 1080), on_screen_texts=["TOO FAST"],
    )
    assert "Dialogue: 1," not in path.read_text()


def test_on_screen_texts_length_mismatch_raises(tmp_path):
    scene = _scene(["hello"], 1.0)
    try:
        build_ass([scene], tmp_path / "captions.ass", resolution=(1920, 1080), on_screen_texts=[])
    except ValueError:
        pass
    else:
        raise AssertionError("expected a ValueError for mismatched on_screen_texts length")


def test_omitting_on_screen_texts_keeps_old_behaviour(tmp_path):
    scene = _scene(["hello", "world"], 2.0)
    path = build_ass([scene], tmp_path / "captions.ass", resolution=(1920, 1080))
    assert "Style: Emphasis" in path.read_text()
    assert "Dialogue: 1," not in path.read_text()
