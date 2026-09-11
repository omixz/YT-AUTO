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
import traceback

from youtube_automation.config import PipelineConfig
from youtube_automation.pipeline import run


def _escape_for_annotation(text: str) -> str:
    """Escapes a string for a GitHub Actions workflow command value, per
    https://docs.github.com/actions/using-workflows/workflow-commands-for-github-actions
    (order matters: escape % first, or the %0A/%0D we add get double-escaped)."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", help="Override the next topic instead of pulling from the queue.")
    parser.add_argument("--format", choices=["shorts", "longform"], default=None, help="Force a specific format instead of letting the bandit pick one.")
    parser.add_argument("--dry-run", action="store_true", help="Build the video but skip uploading.")
    parser.add_argument("--config", default=None, help="Path to a channel config YAML (default: config/channel.yaml).")
    parser.add_argument("--publish-at", default=None, help="RFC3339 timestamp to schedule the YouTube release.")
    parser.add_argument("--publish-now", action="store_true", help="Release immediately instead of scheduling the next optimal slot.")
    parser.add_argument("--keep-work-dir", action="store_true", help="Keep per-scene scratch files after the run.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = PipelineConfig.load(args.config)
    try:
        manifest = run(
            config,
            topic_override=args.topic,
            dry_run=args.dry_run,
            publish_at=args.publish_at,
            publish_now=args.publish_now,
            keep_work_dir=args.keep_work_dir,
            format_override=args.format,
        )
    except Exception:
        # Surface the real failure as a GitHub Actions error annotation, so it's
        # readable via the plain Checks/annotations REST API even in contexts
        # that can't follow the Azure Blob Storage redirect GitHub uses for full
        # job log downloads (e.g. a sandboxed debugging environment restricted
        # to a fixed domain allowlist that doesn't include Azure blob storage).
        print(f"::error title=Pipeline failed::{_escape_for_annotation(traceback.format_exc())}")
        raise

    print("\n=== Run complete ===")
    for key, value in manifest.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
