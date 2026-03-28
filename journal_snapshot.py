from __future__ import annotations

import argparse
import json

from utils.journal_snapshot import build_journal_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Print a compact trading journal snapshot as JSON.")
    parser.add_argument("--path", default=None, help="Optional path to a journal JSONL file.")
    parser.add_argument("--limit", type=int, default=10, help="How many recent entries to include.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON output.")
    args = parser.parse_args()

    snapshot = build_journal_snapshot(path=args.path, tail_limit=args.limit)
    if args.pretty:
        print(json.dumps(snapshot, indent=2, ensure_ascii=True, sort_keys=True))
        return

    print(json.dumps(snapshot, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
