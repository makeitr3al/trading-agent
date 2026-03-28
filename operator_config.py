from __future__ import annotations

import argparse
import json

from utils.operator_config import (
    SUPPORTED_ENVIRONMENTS,
    SUPPORTED_MODES,
    build_operator_payload,
    export_operator_env_shell,
    update_operator_config,
)


def _print_payload(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the Home Assistant operator configuration for the trading agent.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_parser = subparsers.add_parser("show", help="Print the current operator configuration as JSON.")
    show_parser.add_argument("--path", default=None)

    set_parser = subparsers.add_parser("set", help="Update one or more operator configuration values.")
    set_parser.add_argument("--path", default=None)
    set_parser.add_argument("--mode", choices=SUPPORTED_MODES)
    set_parser.add_argument("--environment", choices=SUPPORTED_ENVIRONMENTS)
    set_parser.add_argument("--leverage", type=int)
    set_parser.add_argument("--markets")
    set_parser.add_argument("--scheduling-enabled", choices=["true", "false"])
    set_parser.add_argument("--schedule-time")

    reset_parser = subparsers.add_parser("reset", help="Reset the operator configuration back to defaults.")
    reset_parser.add_argument("--path", default=None)

    export_parser = subparsers.add_parser("export-env", help="Print shell export lines for the resolved operator configuration.")
    export_parser.add_argument("--path", default=None)

    args = parser.parse_args()

    try:
        if args.command == "show":
            _print_payload(build_operator_payload(path=args.path))
            return 0

        if args.command == "set":
            updates: dict[str, object] = {}
            if args.mode is not None:
                updates["mode"] = args.mode
            if args.environment is not None:
                updates["environment"] = args.environment
            if args.leverage is not None:
                updates["leverage"] = args.leverage
            if args.markets is not None:
                updates["markets"] = args.markets
            if args.scheduling_enabled is not None:
                updates["scheduling_enabled"] = args.scheduling_enabled == "true"
            if args.schedule_time is not None:
                updates["schedule_time"] = args.schedule_time
            if not updates:
                raise ValueError("No operator configuration values were provided")
            path, config = update_operator_config(updates, path=args.path)
            _print_payload({"status": "updated", "config_path": str(path), "config": config, "paths": build_operator_payload(path=path)["paths"]})
            return 0

        if args.command == "reset":
            path, config = update_operator_config({}, reset=True, path=args.path)
            _print_payload({"status": "reset", "config_path": str(path), "config": config, "paths": build_operator_payload(path=path)["paths"]})
            return 0

        print(export_operator_env_shell(path=args.path))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
