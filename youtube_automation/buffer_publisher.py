"""Fallback publish path via Buffer's connected YouTube channel.

Deliberately a FALLBACK, not a primary upload path - pipeline.py only calls
this when youtube_uploader.upload_video() raises (e.g. the OAuth token is
expired/revoked, see youtube_auth.py).

Buffer's public docs/examples don't show any YouTube-specific fields, but
the real schema has them - confirmed by GraphQL introspection against a
live account (`__type(name: "CreatePostInput")` -> `metadata` ->
`PostInputMetaData` -> `youtube` -> `YoutubePostMetadataInput`, which has
title/privacy/categoryId/license/notifySubscribers/embeddable/madeForKids).
Posting without it fails outright ("YouTube posts require a title.",
"YouTube posts require a category."), so this isn't optional - it's the
only way a YouTube post via Buffer's API actually works.

Buffer also does not accept direct file uploads (see media_host.py) - the
video must already be hosted at a stable public URL before calling
publish_video() here.

CRITICAL LIMITATION, confirmed against a live account: Buffer's YouTube
integration only supports Shorts (vertical, <=3 minutes) - this is a
YouTube API restriction Buffer inherits, not something Buffer or this code
chooses. A landscape/longform video is rejected outright ("Video must be
vertical (portrait orientation) for YouTube Shorts.", "...no longer than 3
minutes..."), regardless of any field set here. pipeline.py only attempts
this fallback for format == "shorts" for exactly this reason - for
longform, Buffer cannot publish the video under any circumstance, so
attempting it would just add a doomed extra network round-trip before
still failing.
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


def publish_video(
    video_url: str, title: str, description: str, config: PipelineConfig,
    publish_at: Optional[str] = None, privacy_status: str = "public",
    category_id: str = "27", made_for_kids: bool = False,
) -> str:
    """Creates a Buffer post for the connected YouTube channel pointing at
    video_url (must already be a stable, publicly-fetchable URL - see
    media_host.py). Returns Buffer's post id.

    privacy_status/category_id/made_for_kids mirror youtube_uploader.py's
    same-named parameters so pipeline.py can pass through the same
    effective values (e.g. a quality-gate-failure privacy downgrade)
    regardless of which path actually ends up publishing.

    publish_at, if given, must be an ISO 8601 UTC timestamp - Buffer schedules
    the post for that time rather than adding it to the default queue."""
    secrets = config.secrets
    if not secrets.buffer_api_key:
        raise RuntimeError("BUFFER_API_KEY is not set - cannot use the Buffer fallback publish path.")
    if not secrets.buffer_youtube_channel_id:
        raise RuntimeError("BUFFER_YOUTUBE_CHANNEL_ID is not set - cannot use the Buffer fallback publish path.")

    post_input = {
        "text": description,
        "channelId": secrets.buffer_youtube_channel_id,
        "schedulingType": "automatic",
        "assets": [{"video": {"url": video_url}}],
        "metadata": {
            "youtube": {
                "title": title[:100],
                "privacy": privacy_status,
                "categoryId": category_id,
                "license": "youtube",
                "notifySubscribers": True,
                "embeddable": True,
                "madeForKids": made_for_kids,
            },
        },
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
