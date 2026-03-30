from __future__ import annotations

import argparse
import json
from pathlib import Path

from utils.live_status import build_live_status_payload, write_live_status


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a live account status JSON for the Trading Agent admin panel.")
    parser.add_argument("--environment", default=None)
    parser.add_argument("--account-unrealized-pnl", type=float, default=None)
    parser.add_argument("--account-open-positions-count", type=int, default=0)
    parser.add_argument("--websocket-connected", choices=["true", "false"], default="false")
    parser.add_argument("--source", default="poll")
    parser.add_argument("--last-error", default=None)
    parser.add_argument("--updated-at", default=None)
    parser.add_argument("--output-path", default=None)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    payload = build_live_status_payload(
        environment=args.environment,
        account_unrealized_pnl=args.account_unrealized_pnl,
        account_open_positions_count=args.account_open_positions_count,
        websocket_connected=args.websocket_connected == "true",
        source=args.source,
        last_error=args.last_error,
        updated_at=args.updated_at,
    )

    rendered = json.dumps(payload, ensure_ascii=True, indent=2 if args.pretty else None, sort_keys=args.pretty)
    if args.output_path:
        output_path = Path(args.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_live_status(payload, path=output_path)
        return

    print(rendered)


if __name__ == "__main__":
    main()
