from unittest.mock import MagicMock, patch

import pytest

from youtube_automation import media_host
from youtube_automation.config import PipelineConfig


def _config():
    config = PipelineConfig.load()
    config.secrets.media_host_bucket = "my-bucket"
    config.secrets.media_host_access_key = "key"
    config.secrets.media_host_secret_key = "secret"
    return config


def test_upload_public_uses_explicit_public_base_url(tmp_path):
    config = _config()
    config.secrets.media_host_public_base_url = "https://media.example.com"
    path = tmp_path / "final.mp4"
    path.write_bytes(b"fake video")

    fake_client = MagicMock()
    with patch("boto3.client", return_value=fake_client) as client_factory:
        url = media_host.upload_public(path, "run123.mp4", config)

    assert url == "https://media.example.com/run123.mp4"
    fake_client.upload_file.assert_called_once()
    client_factory.assert_called_once()


def test_upload_public_falls_back_to_s3_url_when_no_base_url_or_endpoint(tmp_path):
    config = _config()
    path = tmp_path / "final.mp4"
    path.write_bytes(b"fake video")

    with patch("boto3.client", return_value=MagicMock()):
        url = media_host.upload_public(path, "run123.mp4", config)

    assert url == "https://my-bucket.s3.auto.amazonaws.com/run123.mp4"


def test_upload_public_raises_when_not_configured(tmp_path):
    config = PipelineConfig.load()
    path = tmp_path / "final.mp4"
    path.write_bytes(b"fake video")
    with pytest.raises(RuntimeError, match="MEDIA_HOST_BUCKET"):
        media_host.upload_public(path, "run123.mp4", config)
