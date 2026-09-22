#!/usr/bin/env python3
"""Merge shard summary.csv files from backtest_market_screener into one ranked report."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtest.metrics import RANKING_FORMULA  # noqa: E402
from backtest.screener import render_report_md, sort_go_rows  # noqa: E402


def _load_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge screener shard summaries into global ranking.")
    ap.add_argument(
        "summaries",
        nargs="+",
        type=Path,
        help="One or more summary.csv paths (shard outputs)",
    )
    ap.add_argument("--out", type=Path, required=True, help="Output directory for merged artifacts")
    args = ap.parse_args()

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in args.summaries:
        for row in _load_rows(path):
            market = str(row.get("market") or "")
            if not market or market in seen:
                continue
            seen.add(market)
            # Coerce numeric fields used for ranking
            for key in ("calmar", "return_pct", "n_trades", "max_drawdown_pct", "net_pnl"):
                raw = row.get(key, "")
                if raw == "" or raw is None:
                    continue
                try:
                    if key == "n_trades":
                        row[key] = int(float(raw))
                    else:
                        row[key] = float(raw)
                except (TypeError, ValueError):
                    pass
            rows.append(row)

    rows = sort_go_rows(rows)
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    fieldnames = list(rows[0].keys()) if rows else ["market", "decision", "rank"]
    # Prefer canonical order from first file
    if args.summaries:
        with args.summaries[0].open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                fieldnames = list(reader.fieldnames)
                if "rank" not in fieldnames:
                    fieldnames = ["rank"] + fieldnames

    summary_path = out_dir / "summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as sf:
        w = csv.DictWriter(sf, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})

    shortlist = [r for r in rows if str(r.get("decision")) == "GO"]
    with (out_dir / "shortlist.csv").open("w", newline="", encoding="utf-8") as sf:
        w = csv.DictWriter(sf, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in shortlist:
            w.writerow({k: r.get(k, "") for k in fieldnames})

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_meta = {
        "generated_at_utc": ts,
        "merged_from": [str(p) for p in args.summaries],
        "ranking": RANKING_FORMULA,
        "n_markets": len(rows),
        "n_go": len(shortlist),
        "assumptions": [
            "Merged shard summaries; ranking recomputed globally by Calmar.",
            "Duplicate markets across shards: first file wins.",
        ],
    }
    (out_dir / "run.json").write_text(json.dumps(run_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "report.md").write_text(
        render_report_md(rows=rows, run_meta=run_meta),
        encoding="utf-8",
    )
    print(f"Merged {len(rows)} markets ({len(shortlist)} GO) → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
