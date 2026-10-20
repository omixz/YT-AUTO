#!/usr/bin/env python3
"""One-time: remove zero scores that private (gate-failed) videos wrongly added to the growth bandit.
Safe to re-run: it only removes zeros up to the count of scored-but-private ledger records not yet repaired."""
import json
from pathlib import Path

from youtube_automation import growth_ledger as gl
from youtube_automation.config import PipelineConfig

cfg = PipelineConfig.load("config/channel.yaml")
path = Path(gl.ROOT) / cfg.growth.stats_file
stats = json.loads(path.read_text(encoding="utf-8"))
if any(e.get("repaired_private_zeros") is not None for e in stats.values()):
    raise SystemExit("Already repaired - nothing to do.")
before = {k: round(v["avg_score"], 1) for k, v in stats.items()}
stats = gl.repair_stats(stats, json.loads((Path(gl.ROOT) / gl.LEDGER_PATH).read_text(encoding="utf-8")))
path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
for k, v in stats.items():
    print(f"{k:34} avg {before[k]:5.1f} -> {v['avg_score']:5.1f}  (n={v['samples']}, removed {v.get('repaired_private_zeros', 0)})")
