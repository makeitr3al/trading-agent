from __future__ import annotations

import argparse
import json
from pathlib import Path

from utils.run_summary import build_run_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a compact summary JSON for the latest trading-agent run.")
    parser.add_argument("--mode", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--finished-at", required=True)
    parser.add_argument("--exit-code", required=True, type=int)
    parser.add_argument("--journal-path", default=None)
    parser.add_argument("--test-status-path", default=None)
    parser.add_argument("--output-path", default=None)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    payload = build_run_summary(
        mode=args.mode,
        environment=args.environment,
        started_at=args.started_at,
        finished_at=args.finished_at,
        exit_code=args.exit_code,
        journal_path=args.journal_path,
        test_status_path=args.test_status_path,
    )

    rendered = json.dumps(payload, ensure_ascii=True, indent=2 if args.pretty else None, sort_keys=args.pretty)
    if args.output_path:
        output_path = Path(args.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
        return

    print(rendered)


if __name__ == "__main__":
    main()
