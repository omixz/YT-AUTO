#!/usr/bin/env python3
"""CLI entrypoint for one automated-channel run.

Examples:
    python run_pipeline.py --dry-run
    python run_pipeline.py --topic "Why cats purr" --dry-run
    python run_pipeline.py --publish-at 2026-07-15T15:00:00Z
"""
from __future__ import annotations

import argparse
import logging

from youtube_automation.config import PipelineConfig
from youtube_automation.pipeline import run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", help="Override the next topic instead of pulling from the queue.")
    parser.add_argument("--dry-run", action="store_true", help="Build the video but skip uploading.")
    parser.add_argument("--config", default=None, help="Path to a channel config YAML (default: config/channel.yaml).")
    parser.add_argument("--publish-at", default=None, help="RFC3339 timestamp to schedule the YouTube release.")
    parser.add_argument("--keep-work-dir", action="store_true", help="Keep per-scene scratch files after the run.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = PipelineConfig.load(args.config)
    manifest = run(
        config,
        topic_override=args.topic,
        dry_run=args.dry_run,
        publish_at=args.publish_at,
        keep_work_dir=args.keep_work_dir,
    )

    print("\n=== Run complete ===")
    for key, value in manifest.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
