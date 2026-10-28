#!/usr/bin/env python3
"""End-to-end TikTok probe WITHOUT publishing: renders a 2s vertical clip, hosts it on a GitHub Release, and asks
Buffer to save it as a DRAFT on the TikTok channel. Proves the hosting URL, API shape and TikTok metadata all work.
Delete the draft in Buffer afterwards. Writes probe_report.md."""
import subprocess
import traceback
from pathlib import Path

from youtube_automation import buffer_publisher, media_host
from youtube_automation.config import PipelineConfig

out = ["## TikTok probe (draft only, nothing published)", ""]
try:
    cfg = PipelineConfig.load("config/channel.yaml")
    clip = Path("probe.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=3", "-f", "lavfi",
                    "-i", "anullsrc=r=44100:cl=stereo", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)], check=True)
    url = media_host.upload_public(clip, "probe.mp4", cfg)
    out.append(f"- Hosted at: {url}")
    post_id = buffer_publisher.publish_tiktok(url, "Probe - safe to delete", cfg, title="Probe", save_to_draft=True)
    out.append(f"- **Buffer accepted the draft: post id `{post_id}`** - the whole chain works. Delete the draft in Buffer.")
except Exception:
    out += ["- **FAILED**", "```", traceback.format_exc()[-1800:], "```"]
Path("probe_report.md").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
