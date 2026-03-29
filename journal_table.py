from __future__ import annotations

import argparse
import json
from pathlib import Path

from utils.journal_table import build_journal_table


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a Home Assistant friendly journal table JSON.")
    parser.add_argument("--path", default=None, help="Optional path to a journal JSONL file.")
    parser.add_argument("--output-path", default=None, help="Optional JSON output path.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON output.")
    args = parser.parse_args()

    payload = build_journal_table(path=args.path)
    rendered = json.dumps(payload, ensure_ascii=True, indent=2 if args.pretty else None, sort_keys=args.pretty)
    if args.output_path:
        output_path = Path(args.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
        return

    print(rendered)


if __name__ == "__main__":
    main()
