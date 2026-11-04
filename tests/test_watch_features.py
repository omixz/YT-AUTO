from pathlib import Path

from youtube_automation import growth_ledger as gl, subtitles
from youtube_automation.config import PipelineConfig
from youtube_automation.tts import SceneAudio, WordCue


def _audio():
    return [SceneAudio(scene_index=0, audio_path=Path("a.mp3"), duration=2.0, cues=[WordCue("Hello", 0.1, 0.5), WordCue("world", 0.6, 1.0)])]


def test_center_position_uses_middle_alignment(tmp_path):
    for pos, an in (("center", ",5,60,60,"), ("bottom", ",2,60,60,")):
        ass = subtitles.build_ass(_audio(), tmp_path / f"{pos}.ass", (1080, 1920), position=pos).read_text()
        assert an in ass.split("Style: Default")[1].split("\n")[0]


def test_channel_config_centers_captions():
    assert PipelineConfig.load("config/channel.yaml").video.subtitle_position == "center"


def test_related_videos_are_public_same_niche_newest_first(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(gl, "ROOT", tmp_path)
    recs = [{"video_id": "old", "niche": "n", "format": "longform", "published_at": "2026-10-01", "privacy_status": "public", "title": "a"},
            {"video_id": "new", "niche": "n", "format": "longform", "published_at": "2026-10-05", "privacy_status": "public", "title": "b"},
            {"video_id": "priv", "niche": "n", "format": "longform", "published_at": "2026-10-09", "privacy_status": "private", "title": "c"},
            {"video_id": "other", "niche": "x", "format": "longform", "published_at": "2026-10-09", "privacy_status": "public", "title": "d"}]
    p = tmp_path / gl.LEDGER_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(recs))
    assert [r["video_id"] for r in gl.related_videos("n")] == ["new", "old"]
