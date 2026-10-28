from pathlib import Path
from types import SimpleNamespace

import pytest

from youtube_automation import buffer_publisher, crosspost, media_host


def _cfg(**secrets):
    base = dict(buffer_api_key="k", buffer_tiktok_channel_id="ch1", github_token=None, github_repository=None,
                media_host_bucket=None, media_host_access_key=None, media_host_secret_key=None)
    base.update(secrets)
    return SimpleNamespace(secrets=SimpleNamespace(**base), upload=SimpleNamespace(crosspost_tiktok=True, tiktok_hashtags="#h"))


KW = dict(format_name="shorts", privacy="public", passed_gate=True, dry_run=False, video_path=Path("v.mp4"), run_id="r", title="T")


@pytest.mark.parametrize("override", [dict(format_name="longform"), dict(privacy="private"), dict(passed_gate=False), dict(dry_run=True)])
def test_only_public_gate_passed_shorts_are_crossposted(monkeypatch, override):
    monkeypatch.setattr(media_host, "upload_public", lambda *a: pytest.fail("must not host"))
    assert crosspost.tiktok(_cfg(), **{**KW, **override}) is None


def test_skipped_silently_without_credentials(monkeypatch):
    monkeypatch.setattr(media_host, "upload_public", lambda *a: pytest.fail("must not host"))
    assert crosspost.tiktok(_cfg(buffer_tiktok_channel_id=None), **KW) is None


def test_posts_and_never_raises(monkeypatch):
    monkeypatch.setattr(media_host, "upload_public", lambda path, key, cfg: "https://x/v.mp4")
    seen = {}
    monkeypatch.setattr(buffer_publisher, "publish_tiktok", lambda url, caption, cfg, title="": seen.update(url=url, caption=caption) or "post9")
    assert crosspost.tiktok(_cfg(), **KW) == "post9" and seen["url"] == "https://x/v.mp4" and "#h" in seen["caption"]
    monkeypatch.setattr(buffer_publisher, "publish_tiktok", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert crosspost.tiktok(_cfg(), **KW) is None


def test_publish_tiktok_tries_share_now_then_queue(monkeypatch):
    calls = []

    class R:
        def __init__(self, status, body): self.status_code, self._b, self.text = status, body, str(body)
        def json(self): return self._b

    def fake_post(url, headers, json, timeout):
        inp = json["variables"]["input"]
        assert inp["needsApproval"] is False and inp["channelId"] == "ch1"
        calls.append((inp["mode"], "metadata" in inp))
        ok = inp["mode"] == "addToQueue" and "metadata" not in inp      # worst case: only the plainest request is accepted
        return R(200, {"data": {"createPost": {"post": {"id": "p1"}}}}) if ok else R(200, {"errors": [{"message": "rejected"}]})

    monkeypatch.setattr(buffer_publisher.requests, "post", fake_post)
    assert buffer_publisher.publish_tiktok("https://x/v.mp4", "cap", _cfg()) == "p1" and calls == [("shareNow", True), ("shareNow", False), ("addToQueue", True), ("addToQueue", False)]


def test_github_release_hosting_is_used_when_no_bucket(monkeypatch, tmp_path):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"abc")
    monkeypatch.setattr(media_host, "_upload_github_release", lambda path, key, cfg: f"https://gh/{key}")
    assert media_host.upload_public(f, "k.mp4", _cfg(github_token="t", github_repository="o/r")) == "https://gh/k.mp4"
