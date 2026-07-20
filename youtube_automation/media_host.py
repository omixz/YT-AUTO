"""Uploads a file to an S3-compatible bucket and returns its public URL.

Only used by buffer_publisher.py's fallback path: Buffer's API requires a
stable public URL for video assets (it doesn't accept direct file uploads -
see buffer_publisher.py's module docstring), and nothing else in this
pipeline needs public hosting. Works against real AWS S3 or any
S3-compatible provider (Cloudflare R2, Backblaze B2, ...) via
media_host_endpoint_url; leave that blank for real AWS S3.
"""
from __future__ import annotations

import logging
from pathlib import Path

import boto3

from .config import PipelineConfig

logger = logging.getLogger(__name__)


def _client(config: PipelineConfig):
    secrets = config.secrets
    if not (secrets.media_host_bucket and secrets.media_host_access_key and secrets.media_host_secret_key):
        raise RuntimeError(
            "Media hosting is not configured - MEDIA_HOST_BUCKET, MEDIA_HOST_ACCESS_KEY, and "
            "MEDIA_HOST_SECRET_KEY must all be set for the Buffer fallback publish path to host a "
            "public video URL."
        )
    return boto3.client(
        "s3",
        endpoint_url=secrets.media_host_endpoint_url or None,
        aws_access_key_id=secrets.media_host_access_key,
        aws_secret_access_key=secrets.media_host_secret_key,
        region_name=secrets.media_host_region,
    )


def upload_public(path: Path, key: str, config: PipelineConfig) -> str:
    """Uploads path to the configured bucket under `key`, makes it publicly
    readable, and returns the URL Buffer should fetch it from."""
    secrets = config.secrets
    client = _client(config)
    content_type = "video/mp4" if path.suffix == ".mp4" else "image/jpeg"

    client.upload_file(
        str(path), secrets.media_host_bucket, key,
        ExtraArgs={"ACL": "public-read", "ContentType": content_type},
    )

    if secrets.media_host_public_base_url:
        url = f"{secrets.media_host_public_base_url.rstrip('/')}/{key}"
    elif secrets.media_host_endpoint_url:
        url = f"{secrets.media_host_endpoint_url.rstrip('/')}/{secrets.media_host_bucket}/{key}"
    else:
        url = f"https://{secrets.media_host_bucket}.s3.{secrets.media_host_region}.amazonaws.com/{key}"

    logger.info("Hosted %s at %s", path.name, url)
    return url
