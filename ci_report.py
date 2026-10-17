#!/usr/bin/env python3
"""Post-run reporting for GitHub Actions.

Reads the newest ``output/*/manifest.json`` and:
  * writes a human-readable job summary ($GITHUB_STEP_SUMMARY),
  * when a real (non-dry-run) upload tripped the quality gate, writes
    ``issue_body.md`` and sets ``needs_review=true`` / ``title`` as step outputs
    so the workflow can open a review issue.

Without this, a gate-failed video is uploaded as ``private`` and nobody is told.
The title is untrusted (LLM-generated): the workflow must pass it to ``gh`` via
an env var, never by inlining ``${{ }}`` into a shell script.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def latest_manifest(output_dir: Path) -> dict | None:
    """Newest manifest by file mtime; None if no run produced one."""
    manifests = sorted(output_dir.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime)
    if not manifests:
        return None
    return json.loads(manifests[-1].read_text(encoding="utf-8"))


def build_summary(m: dict) -> str:
    gate = "passed" if m.get("passed_quality_gate") else "FAILED"
    lines = [
        f"## {m.get('title', '(untitled)')}",
        "",
        f"- **Format:** {m.get('format')}  |  **Niche:** {m.get('niche')}",
        f"- **Topic:** {m.get('topic')}",
        f"- **Quality gate:** {gate}",
    ]
    if m.get("youtube_url"):
        lines.append(f"- **Video:** {m['youtube_url']} ({m.get('privacy_status')})")
        if m.get("publish_at"):
            lines.append(f"- **Scheduled for:** {m['publish_at']}")
    else:
        lines.append("- **Upload:** none (dry run or failed before upload)")
    reasons = m.get("quality_gate_reasons") or []
    if reasons:
        lines += ["", "### Quality gate reasons", *[f"- {r}" for r in reasons]]
    return "\n".join(lines) + "\n"


def needs_review(m: dict) -> bool:
    """A real upload happened AND the gate failed -> a human must look at it."""
    return bool(m.get("youtube_video_id")) and not m.get("passed_quality_gate", True)


def build_issue_body(m: dict) -> str:
    return (
        "The quality gate rejected a video, so it was uploaded with a restricted "
        "privacy status instead of going public. Review it in YouTube Studio, then "
        "publish or delete it.\n\n" + build_summary(m)
    )


def _set_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            # Single-line values only; newlines would let a value inject extra outputs.
            fh.write(f"{key}={value.replace(chr(10), ' ').replace(chr(13), ' ')}\n")


def main() -> int:
    manifest = latest_manifest(ROOT / "output")
    if manifest is None:
        print("No manifest found - the run failed before producing one.")
        return 0
    summary = build_summary(manifest)
    print(summary)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(summary)
    if needs_review(manifest):
        (ROOT / "issue_body.md").write_text(build_issue_body(manifest), encoding="utf-8")
        _set_output("needs_review", "true")
        _set_output("title", str(manifest.get("title", "untitled"))[:120])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
