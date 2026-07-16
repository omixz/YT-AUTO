from PIL import Image

from youtube_automation import thumbnail
from youtube_automation.visuals import VisualAsset


def _fake_image_asset(tmp_path):
    path = tmp_path / "frame.jpg"
    Image.new("RGB", (1920, 1080), (40, 90, 140)).save(path)
    return VisualAsset(kind="image", path=path)


def test_pick_highlight_word_prefers_power_word():
    words = "THE SECRET THAT DOOMED THE EMPIRE".split()
    assert thumbnail._pick_highlight_word(words) == "SECRET"


def test_pick_highlight_word_falls_back_to_number():
    words = "HOW 12 SOLDIERS HELD THE LINE".split()
    assert thumbnail._pick_highlight_word(words) == "12"


def test_pick_highlight_word_falls_back_to_last_word():
    words = "A QUIET AFTERNOON IN ROME".split()
    assert thumbnail._pick_highlight_word(words) == "ROME"


def test_generate_produces_correctly_sized_thumbnail(tmp_path):
    asset = _fake_image_asset(tmp_path)
    out = thumbnail.generate("The Secret That Doomed an Empire", asset, tmp_path, tmp_path / "thumb.jpg")
    assert out.exists()
    with Image.open(out) as img:
        assert img.size == thumbnail.THUMB_SIZE


def test_generate_renders_highlight_color_somewhere(tmp_path):
    asset = _fake_image_asset(tmp_path)
    out = thumbnail.generate("The Secret That Doomed an Empire", asset, tmp_path, tmp_path / "thumb.jpg")
    with Image.open(out) as img:
        pixels = img.getdata()
        assert any(
            abs(r - thumbnail.HIGHLIGHT_COLOR[0]) < 10
            and abs(g - thumbnail.HIGHLIGHT_COLOR[1]) < 10
            and abs(b - thumbnail.HIGHLIGHT_COLOR[2]) < 10
            for r, g, b in pixels
        ), "no pixel close to the highlight color was found - the power word never got rendered"
