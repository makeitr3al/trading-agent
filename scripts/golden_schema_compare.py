from __future__ import annotations

import os
from pathlib import Path
import sys
from statistics import median
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.providers.golden_data_provider import _load_golden_scenario
from data.providers.hyperliquid_historical_provider import HyperliquidHistoricalProvider
from models.candle import Candle
from utils.env_loader import load_hyperliquid_config_from_env


CORE_CANDLE_FIELDS = ("timestamp", "open", "high", "low", "close")


# TODO: Later extend this report with optional distribution comparisons and chart-shape diagnostics.
# TODO: Later add optional JSON export for repeatable scenario review.


def _has_field(item: Any, field_name: str) -> bool:
    if isinstance(item, dict):
        return field_name in item
    return hasattr(item, field_name)



def compare_candle_shape(left: Sequence[Any], right: Sequence[Any]) -> bool:
    if not left or not right:
        return False
    left_item = left[0]
    right_item = right[0]
    return all(_has_field(left_item, field) and _has_field(right_item, field) for field in CORE_CANDLE_FIELDS)



def is_chronologically_sorted(candles: Sequence[Candle]) -> bool:
    return all(candles[index].timestamp <= candles[index + 1].timestamp for index in range(len(candles) - 1))



def summarize_time_spacing(candles: Sequence[Candle]) -> dict[str, float | None]:
    if len(candles) < 2:
        return {"min_seconds": None, "max_seconds": None, "median_seconds": None}

    spacings = [
        (candles[index + 1].timestamp - candles[index].timestamp).total_seconds()
        for index in range(len(candles) - 1)
    ]
    return {
        "min_seconds": min(spacings),
        "max_seconds": max(spacings),
        "median_seconds": float(median(spacings)),
    }



def summarize_candles(candles: Sequence[Candle]) -> dict[str, Any]:
    if not candles:
        return {
            "count": 0,
            "close_min": None,
            "close_max": None,
            "high_min": None,
            "high_max": None,
            "low_min": None,
            "low_max": None,
            "magnitude_ratio": None,
            "spacing_summary": summarize_time_spacing(candles),
        }

    closes = [candle.close for candle in candles]
    highs = [candle.high for candle in candles]
    lows = [candle.low for candle in candles]
    non_zero_magnitudes = [abs(value) for value in closes + highs + lows if abs(value) > 0]
    magnitude_ratio = None
    if non_zero_magnitudes:
        magnitude_ratio = max(non_zero_magnitudes) / min(non_zero_magnitudes)

    return {
        "count": len(candles),
        "close_min": min(closes),
        "close_max": max(closes),
        "high_min": min(highs),
        "high_max": max(highs),
        "low_min": min(lows),
        "low_max": max(lows),
        "magnitude_ratio": magnitude_ratio,
        "spacing_summary": summarize_time_spacing(candles),
    }



def check_candle_consistency(candles: Sequence[Candle]) -> dict[str, Any]:
    invalid_count = 0
    for candle in candles:
        if candle.high < max(candle.open, candle.close):
            invalid_count += 1
            continue
        if candle.low > min(candle.open, candle.close):
            invalid_count += 1
            continue
        if candle.high < candle.low:
            invalid_count += 1

    return {
        "ok": invalid_count == 0,
        "invalid_count": invalid_count,
        "checked_count": len(candles),
    }



def _format_spacing(summary: dict[str, float | None]) -> str:
    if summary["median_seconds"] is None:
        return "insufficient data"
    return (
        f"min={summary['min_seconds']}s, "
        f"max={summary['max_seconds']}s, "
        f"median={summary['median_seconds']}s"
    )



def _format_range(summary: dict[str, Any]) -> str:
    return (
        f"close=[{summary['close_min']}, {summary['close_max']}], "
        f"high=[{summary['high_min']}, {summary['high_max']}], "
        f"low=[{summary['low_min']}, {summary['low_max']}], "
        f"magnitude_ratio={summary['magnitude_ratio']}"
    )



def _recommendation(
    field_structure_match: bool,
    live_sorted: bool,
    golden_sorted: bool,
    live_consistency: dict[str, Any],
    golden_consistency: dict[str, Any],
    live_summary: dict[str, Any],
    golden_summary: dict[str, Any],
) -> str:
    if not field_structure_match or not live_sorted or not golden_sorted:
        return "Golden scenario differs structurally and should be refined."
    if not live_consistency["ok"] or not golden_consistency["ok"]:
        return "Golden scenario fails candle sanity checks and should be refined."

    live_spacing = live_summary["spacing_summary"]["median_seconds"]
    golden_spacing = golden_summary["spacing_summary"]["median_seconds"]
    spacing_mismatch = (
        live_spacing is not None
        and golden_spacing is not None
        and live_spacing != golden_spacing
    )
    magnitude_ratio_gap = False
    if live_summary["magnitude_ratio"] and golden_summary["magnitude_ratio"]:
        larger = max(live_summary["magnitude_ratio"], golden_summary["magnitude_ratio"])
        smaller = min(live_summary["magnitude_ratio"], golden_summary["magnitude_ratio"])
        magnitude_ratio_gap = smaller > 0 and (larger / smaller) > 5

    if spacing_mismatch or magnitude_ratio_gap:
        return "Golden scenario differs notably in spacing/value shape and may need refinement."
    return "Golden scenario appears structurally realistic."



def main() -> None:
    print("Golden schema compare started.")

    try:
        hyperliquid_config = load_hyperliquid_config_from_env()
        golden_scenario_name = (os.getenv("GOLDEN_SCENARIO") or "").strip()
        if not golden_scenario_name:
            raise ValueError("Missing GOLDEN_SCENARIO for schema compare")

        print("Data source live side: Hyperliquid")
        print(f"Golden scenario name: {golden_scenario_name}")
        print(f"Hyperliquid coin: {hyperliquid_config.coin}")
        print(f"interval: {hyperliquid_config.interval}")
        print(f"lookback_bars: {hyperliquid_config.lookback_bars}")

        live_batch = HyperliquidHistoricalProvider(hyperliquid_config).fetch_candles()
        golden_scenario = _load_golden_scenario(golden_scenario_name)
        golden_candles = golden_scenario.candles

        field_structure_match = compare_candle_shape(live_batch.candles, golden_candles)
        live_sorted = is_chronologically_sorted(live_batch.candles)
        golden_sorted = is_chronologically_sorted(golden_candles)
        live_summary = summarize_candles(live_batch.candles)
        golden_summary = summarize_candles(golden_candles)
        live_consistency = check_candle_consistency(live_batch.candles)
        golden_consistency = check_candle_consistency(golden_candles)

        print(f"Live candles count: {live_summary['count']}")
        print(f"Golden candles count: {golden_summary['count']}")
        print(f"Field structure match: {'yes' if field_structure_match else 'no'}")
        print(
            f"Chronological order match: {'yes' if live_sorted and golden_sorted else 'no'}"
        )
        print(f"Timestamp spacing live: {_format_spacing(live_summary['spacing_summary'])}")
        print(f"Timestamp spacing golden: {_format_spacing(golden_summary['spacing_summary'])}")
        print(f"Live value range summary: {_format_range(live_summary)}")
        print(f"Golden value range summary: {_format_range(golden_summary)}")
        print(
            f"Candle consistency live: {'ok' if live_consistency['ok'] else 'not ok'} "
            f"(invalid={live_consistency['invalid_count']})"
        )
        print(
            f"Candle consistency golden: {'ok' if golden_consistency['ok'] else 'not ok'} "
            f"(invalid={golden_consistency['invalid_count']})"
        )
        print(
            _recommendation(
                field_structure_match=field_structure_match,
                live_sorted=live_sorted,
                golden_sorted=golden_sorted,
                live_consistency=live_consistency,
                golden_consistency=golden_consistency,
                live_summary=live_summary,
                golden_summary=golden_summary,
            )
        )
    except Exception as exc:
        print(f"Golden schema compare failed: {exc}")


if __name__ == "__main__":
    main()
