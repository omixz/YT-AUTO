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


def test_vignette_leaves_center_untouched_and_darkens_corners():
    # Regression test: _vignette used to build its mask by drawing ~360
    # concentric 1px ellipse OUTLINES with alpha decreasing INWARD from a
    # 255 (fully opaque) base - center-pixel alpha measured at 192/255
    # (~75% black overlay) instead of ~0, so every thumbnail rendered
    # almost entirely black regardless of intensity, not just the corners.
    w, h = thumbnail.THUMB_SIZE
    img = Image.new("RGB", (w, h), (240, 240, 235))
    out = thumbnail._vignette(img, intensity=0.35)

    center = out.getpixel((w // 2, h // 2))
    corner = out.getpixel((2, 2))

    # Center should be at or extremely close to the original color - a
    # vignette's whole job is to leave the center alone.
    assert all(abs(c - o) < 8 for c, o in zip(center, (240, 240, 235))), (
        f"center pixel {center} was darkened - vignette should leave the center untouched"
    )
    # Corners should be visibly darker than center.
    assert sum(corner) < sum(center) - 30, (
        f"corner pixel {corner} isn't meaningfully darker than center {center}"
    )


def test_all_three_variants_are_not_blown_out_to_black(tmp_path):
    # End-to-end guard for the same bug: with a bright, ordinary-looking
    # source frame, none of the 3 A/B variants should come out looking like
    # a near-black image once vignette + color grading are applied.
    asset = _fake_image_asset(tmp_path)  # a mid-brightness solid color frame
    variants = thumbnail.generate_variants("Nobody Expected What Happened Next", asset, tmp_path, tone="shocking")
    for variant in variants:
        with Image.open(variant.path) as img:
            pixels = list(img.getdata())
            avg_brightness = sum(sum(p) for p in pixels) / (len(pixels) * 3)
        assert avg_brightness > 40, (
            f"{variant.name} average brightness is {avg_brightness:.1f}/255 - looks blown out to black"
        )
