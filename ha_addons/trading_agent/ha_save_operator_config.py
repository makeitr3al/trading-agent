#!/usr/bin/env python3
"""Merge-save operator_config.json for Home Assistant shell_command (preserves unknown keys)."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 9:
        print("usage: ha_save_operator_config.py MODE ENV LEVERAGE MARKETS SCHED_BOOL SCHED_TIME CHALLENGE_ATTEMPT_ID PUSH_BOOL", file=sys.stderr)
        return 2

    mode, environment, leverage_s, markets, sched_s, sched_time, attempt_id, push_s = sys.argv[1:9]
    path = Path("/share/trading-agent-data/operator_config.json")
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except Exception:
            existing = {}

    merged = {
        **existing,
        "mode": mode,
        "environment": environment,
        "leverage": int(leverage_s),
        "markets": markets,
        "scheduling_enabled": sched_s.strip().lower() == "true",
        "schedule_time": sched_time,
        "challenge_id": str(existing.get("challenge_id") or ""),
        "challenge_attempt_id": attempt_id,
        "push_enabled": push_s.strip().lower() == "true",
    }
    path.write_text(json.dumps(merged, ensure_ascii=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
