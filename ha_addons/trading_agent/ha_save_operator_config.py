#!/usr/bin/env python3
"""Merge-save operator_config.json for Home Assistant shell_command (preserves unknown keys)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_DEFAULT_MARKETS_FALLBACK = "BTC,ETH,SOL,XRP"


def _coerce_leverage(raw: str) -> int:
    s = (raw or "").strip()
    if not s:
        return 1
    try:
        n = int(s)
    except ValueError:
        return 1
    return n if n >= 1 else 1


def _coerce_push(raw: str) -> bool:
    return (raw or "").strip().lower() == "true"


def main() -> int:
    if len(sys.argv) != 9:
        print("usage: ha_save_operator_config.py MODE ENV LEVERAGE MARKETS SCHED_BOOL SCHED_TIME CHALLENGE_ATTEMPT_ID PUSH_BOOL", file=sys.stderr)
        return 2

    mode, environment, leverage_s, markets, sched_s, sched_time, attempt_id, push_s = sys.argv[1:9]
    mode_t = str(mode or "").strip()
    env_t = str(environment or "").strip()
    if not mode_t or not env_t:
        print(
            "Refusing to write operator_config.json: mode and environment must be non-empty.\n"
            "If you called shell_command.trading_agent_save_operator_config_haos from Developer Tools "
            "with data: {}, every template argument is empty — use script.trading_agent_save_current_config_haos "
            "or pass the same keys as in home_assistant_scripts_haos_addon.yaml.example (mode, environment, "
            "leverage, markets, scheduling_enabled, schedule_time, challenge_attempt_id, push_enabled).",
            file=sys.stderr,
        )
        return 2

    path = Path((os.environ.get("HA_SAVE_OPERATOR_CONFIG_PATH") or "").strip() or "/share/trading-agent-data/operator_config.json")
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except Exception:
            existing = {}

    markets_stripped = (markets or "").strip()
    if not markets_stripped:
        prev = existing.get("markets")
        markets_stripped = (str(prev).strip() if prev is not None else "") or _DEFAULT_MARKETS_FALLBACK

    merged = {
        **existing,
        "mode": mode_t,
        "environment": env_t,
        "leverage": _coerce_leverage(leverage_s),
        "markets": markets_stripped,
        "scheduling_enabled": sched_s.strip().lower() == "true",
        "schedule_time": sched_time,
        "challenge_id": str(existing.get("challenge_id") or ""),
        "challenge_attempt_id": (attempt_id or "").strip(),
        "push_enabled": _coerce_push(push_s),
    }
    path.write_text(json.dumps(merged, ensure_ascii=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
