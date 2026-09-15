#!/usr/bin/env python3
"""Flip an already-uploaded scheduled/private YouTube video's privacy status.

Used when a video was uploaded with a future publishAt (see scheduling.py)
but you want to release it immediately instead of waiting for its slot -
or the reverse: pull a scheduled/public video back to private.

    python publish_now.py <video_id>              # goes public now
    python publish_now.py <video_id> --private     # unschedule / pull back to private
"""
from __future__ import annotations

import argparse
import logging
import traceback

from youtube_automation.config import PipelineConfig
from youtube_automation.youtube_uploader import set_video_privacy


def _escape_for_annotation(text: str) -> str:
    """See run_pipeline.py's copy of this for the full explanation - kept as
    a small duplicated helper rather than a shared import, since this script
    and run_pipeline.py are both meant to be standalone CLI entrypoints, not
    depend on each other."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_id", help="The YouTube video ID to update.")
    parser.add_argument("--private", action="store_true", help="Set to private instead of public.")
    parser.add_argument("--config", default=None, help="Path to a channel config YAML.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = PipelineConfig.load(args.config)
    target_status = "private" if args.private else "public"
    try:
        status = set_video_privacy(args.video_id, target_status, config)
    except Exception:
        # This script previously had zero error visibility on failure - a
        # real incident (an admin unschedule attempt failing on a scope
        # limitation, see set_video_privacy()'s docstring/youtube_auth.py's
        # SCOPES comment) only ever showed "Process completed with exit code
        # 1" in the Actions UI, with no indication of why. Same fix as
        # run_pipeline.py: surface the real traceback as a GitHub error
        # annotation before re-raising, so it's readable via the plain
        # Checks/annotations REST API.
        print(f"::error title=Unschedule/publish failed::{_escape_for_annotation(traceback.format_exc())}")
        raise
    print(f"\n{args.video_id} is now '{status}': https://youtu.be/{args.video_id}")


if __name__ == "__main__":
    main()
