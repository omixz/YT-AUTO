"""Fallback publish path via Buffer's connected YouTube channel.

Deliberately a FALLBACK, not a primary upload path - pipeline.py only calls
this when youtube_uploader.upload_video() raises (e.g. the OAuth token is
expired/revoked, see youtube_auth.py). Buffer's public GraphQL API has no
documented YouTube-specific fields: no separate title, no tags, no privacy-
status control, and no confirmed custom-thumbnail support for YouTube (only
Instagram/TikTok/Pinterest document a thumbnailOffset). Title and
description are therefore folded into one `text` field and the actual
YouTube-side behavior of everything else is whatever Buffer's own YouTube
integration defaults to - this trades control for "something still gets
posted instead of nothing," which is the right trade only because the
primary path already failed.

Buffer also does not accept direct file uploads (see media_host.py) - the
video must already be hosted at a stable public URL before calling
publish_video() here.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from .config import PipelineConfig

logger = logging.getLogger(__name__)

API_URL = "https://api.buffer.com"

_CREATE_POST_MUTATION = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess {
      post { id }
    }
    ... on MutationError {
      message
    }
  }
}
"""


def _post_text(title: str, description: str) -> str:
    # No separate title field is documented for Buffer's YouTube posts (see
    # module docstring) - lead with the title so it's at least the first
    # thing visible, then the description below.
    return f"{title}\n\n{description}".strip()


def publish_video(
    video_url: str, title: str, description: str, config: PipelineConfig,
    publish_at: Optional[str] = None,
) -> str:
    """Creates a Buffer post for the connected YouTube channel pointing at
    video_url (must already be a stable, publicly-fetchable URL - see
    media_host.py). Returns Buffer's post id.

    publish_at, if given, must be an ISO 8601 UTC timestamp - Buffer schedules
    the post for that time rather than adding it to the default queue."""
    secrets = config.secrets
    if not secrets.buffer_api_key:
        raise RuntimeError("BUFFER_API_KEY is not set - cannot use the Buffer fallback publish path.")
    if not secrets.buffer_youtube_channel_id:
        raise RuntimeError("BUFFER_YOUTUBE_CHANNEL_ID is not set - cannot use the Buffer fallback publish path.")

    post_input = {
        "text": _post_text(title, description),
        "channelId": secrets.buffer_youtube_channel_id,
        "schedulingType": "automatic",
        "assets": [{"video": {"url": video_url}}],
    }
    if publish_at:
        post_input["mode"] = "customScheduled"
        post_input["dueAt"] = publish_at
    else:
        post_input["mode"] = "addToQueue"

    response = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {secrets.buffer_api_key}", "Content-Type": "application/json"},
        json={"query": _CREATE_POST_MUTATION, "variables": {"input": post_input}},
        timeout=60,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Buffer API error {response.status_code}: {response.text[:2000]}")

    data = response.json()
    if data.get("errors"):
        raise RuntimeError(f"Buffer API returned errors: {data['errors']}")

    result = data.get("data", {}).get("createPost", {})
    if result.get("message"):
        raise RuntimeError(f"Buffer rejected the post: {result['message']}")

    post = result.get("post")
    if not post or not post.get("id"):
        raise RuntimeError(f"Buffer API returned an unexpected response: {data}")

    logger.info("Posted to Buffer (YouTube channel %s): post id %s", secrets.buffer_youtube_channel_id, post["id"])
    return post["id"]
