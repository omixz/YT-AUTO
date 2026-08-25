from pathlib import Path

from youtube_automation import assembler
from youtube_automation.tts import SceneAudio, WordCue
from youtube_automation.visuals import VisualAsset
from youtube_automation.config import PipelineConfig, VideoConfig, ChannelConfig, NicheConfig, VoiceConfig, VisualsConfig, AnimationConfig, UploadConfig, QualityConfig, TopicsConfig, GrowthConfig, Secrets


def _config():
    return PipelineConfig(
        channel=ChannelConfig(name="Test", audience="General", tone="Casual"),
        niches=[NicheConfig(key="test", niche="test")],
        video=VideoConfig(formats={"shorts": {"target_seconds": 60}}),
        voice=VoiceConfig(),
        visuals=VisualsConfig(),
        animation=AnimationConfig(),
        upload=UploadConfig(),
        quality=QualityConfig(),
        topics=TopicsConfig(),
        growth=GrowthConfig(),
        secrets=Secrets(),
    )


def _scene_audio(duration):
    cues = [WordCue(text="test", start=0.0, end=duration)]
    return SceneAudio(scene_index=0, audio_path=__file__, duration=duration, cues=cues)


def _make_test_image(path, w=320, h=240):
    from PIL import Image
    Image.new("RGB", (w, h), (128, 64, 32)).save(str(path))


def test_build_video_segment_image(tmp_path):
    cfg = _config()
    img = tmp_path / "test.png"
    _make_test_image(img)
    out = tmp_path / "seg.mp4"
    assembler.build_video_segment(VisualAsset(kind="image", path=img), 2.0, cfg, out)
    assert out.exists() and out.stat().st_size > 0


def test_build_video_segment_accepts_scene_role(tmp_path):
    cfg = _config()
    img = tmp_path / "test.png"
    _make_test_image(img)
    for role in ("hook", "build", "insight"):
        out = tmp_path / f"seg_{role}.mp4"
        assembler.build_video_segment(VisualAsset(kind="image", path=img), 2.0, cfg, out, scene_role=role)
        assert out.exists() and out.stat().st_size > 0


def test_crossfade_segments_produces_output(tmp_path):
    cfg = _config()
    img = tmp_path / "test.png"
    _make_test_image(img)
    seg1 = tmp_path / "s1.mp4"
    seg2 = tmp_path / "s2.mp4"
    assembler.build_video_segment(VisualAsset(kind="image", path=img), 3.0, cfg, seg1)
    assembler.build_video_segment(VisualAsset(kind="image", path=img), 3.0, cfg, seg2)
    out = tmp_path / "out.mp4"
    assembler._crossfade_segments([seg1, seg2], [3.0, 3.0], 0.4, out, tmp_path)
    assert out.exists() and out.stat().st_size > 0


def test_crossfade_single_segment_copies(tmp_path):
    cfg = _config()
    img = tmp_path / "test.png"
    _make_test_image(img)
    seg = tmp_path / "s1.mp4"
    assembler.build_video_segment(VisualAsset(kind="image", path=img), 2.0, cfg, seg)
    out = tmp_path / "out.mp4"
    assembler._crossfade_segments([seg], [2.0], 0.4, out, tmp_path)
    assert out.exists() and out.stat().st_size > 0


def test_concat_segments_fallback(tmp_path):
    cfg = _config()
    img = tmp_path / "test.png"
    _make_test_image(img)
    seg1 = tmp_path / "s1.mp4"
    seg2 = tmp_path / "s2.mp4"
    assembler.build_video_segment(VisualAsset(kind="image", path=img), 2.0, cfg, seg1)
    assembler.build_video_segment(VisualAsset(kind="image", path=img), 2.0, cfg, seg2)
    out = tmp_path / "out.mp4"
    assembler._concat_segments([seg1, seg2], out, tmp_path)
    assert out.exists() and out.stat().st_size > 0
