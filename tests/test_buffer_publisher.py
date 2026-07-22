import json
from unittest.mock import patch

import pytest
import requests

from youtube_automation import buffer_publisher
from youtube_automation.config import PipelineConfig


def _config():
    config = PipelineConfig.load()
    config.secrets.buffer_api_key = "test-buffer-key"
    config.secrets.buffer_youtube_channel_id = "channel-123"
    return config


def _response(status_code, payload):
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(payload).encode("utf-8")
    return response


def test_publish_video_returns_post_id_on_success():
    ok = _response(200, {"data": {"createPost": {"post": {"id": "post-1"}}}})
    with patch("requests.post", return_value=ok) as post:
        post_id = buffer_publisher.publish_video(
            "https://example.com/video.mp4", "Title", "Description", _config())
    assert post_id == "post-1"
    sent_input = post.call_args.kwargs["json"]["variables"]["input"]
    assert sent_input["channelId"] == "channel-123"
    assert sent_input["assets"] == [{"video": {"url": "https://example.com/video.mp4"}}]
    assert sent_input["mode"] == "addToQueue"
    assert sent_input["text"] == "Description"


def test_publish_video_sends_youtube_metadata_buffer_actually_requires():
    # Buffer's public docs/examples don't show these fields, but posting
    # without them fails outright - see buffer_publisher.py's module
    # docstring for how this was confirmed via GraphQL introspection.
    ok = _response(200, {"data": {"createPost": {"post": {"id": "post-1"}}}})
    with patch("requests.post", return_value=ok) as post:
        buffer_publisher.publish_video(
            "https://example.com/video.mp4", "Title", "Description", _config(),
            privacy_status="unlisted", category_id="27", made_for_kids=True,
        )
    yt_metadata = post.call_args.kwargs["json"]["variables"]["input"]["metadata"]["youtube"]
    assert yt_metadata == {
        "title": "Title",
        "privacy": "unlisted",
        "categoryId": "27",
        "license": "youtube",
        "notifySubscribers": True,
        "embeddable": True,
        "madeForKids": True,
    }


def test_publish_video_uses_custom_scheduled_when_publish_at_given():
    ok = _response(200, {"data": {"createPost": {"post": {"id": "post-2"}}}})
    with patch("requests.post", return_value=ok) as post:
        buffer_publisher.publish_video(
            "https://example.com/video.mp4", "Title", "Description", _config(),
            publish_at="2026-01-01T12:00:00Z",
        )
    sent_input = post.call_args.kwargs["json"]["variables"]["input"]
    assert sent_input["mode"] == "customScheduled"
    assert sent_input["dueAt"] == "2026-01-01T12:00:00Z"


def test_publish_video_raises_on_mutation_error():
    err = _response(200, {"data": {"createPost": {"message": "channel not found"}}})
    with patch("requests.post", return_value=err):
        with pytest.raises(RuntimeError, match="channel not found"):
            buffer_publisher.publish_video("https://example.com/v.mp4", "T", "D", _config())


def test_publish_video_raises_when_not_configured():
    config = PipelineConfig.load()
    config.secrets.buffer_api_key = None
    with pytest.raises(RuntimeError, match="BUFFER_API_KEY"):
        buffer_publisher.publish_video("https://example.com/v.mp4", "T", "D", config)
