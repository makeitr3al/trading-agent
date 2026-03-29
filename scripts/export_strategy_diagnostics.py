from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.hyperliquid_config import HyperliquidConfig
from config.strategy_config import StrategyConfig, build_strategy_config
from data.providers.hyperliquid_historical_provider import (
    HyperliquidHistoricalProvider,
    compute_time_range_ms,
)
from models.candle import Candle
from scripts.find_historical_reference_cases import (
    _calculate_window_diagnostics,
    _resolve_replay_warmup_bars,
)
from strategy.engine import run_strategy_cycle
from utils.env_loader import load_hyperliquid_config_from_env


ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export per-bar strategy diagnostics for a historical market window.",
    )
    parser.add_argument("--coin", help="Hyperliquid coin, for example BTC")
    parser.add_argument("--interval", help="Hyperliquid interval, for example 1d")
    parser.add_argument("--lookback-bars", type=int, default=220)
    parser.add_argument(
        "--end-date",
        help="UTC end date in YYYY-MM-DD format. The export includes candles up to this date.",
    )
    parser.add_argument("--min-warmup-bars", type=int, default=150)
    parser.add_argument("--output-json", help="Optional JSON output path")
    parser.add_argument("--output-csv", help="Optional CSV output path")
    return parser.parse_args()


def _resolve_base_hyperliquid_config(args: argparse.Namespace) -> HyperliquidConfig:
    env_config = load_hyperliquid_config_from_env()
    return env_config.model_copy(
        update={
            "coin": args.coin or env_config.coin,
            "interval": args.interval or env_config.interval,
            "lookback_bars": args.lookback_bars,
        }
    )


def _resolve_end_ms(end_date: str | None) -> int | None:
    if end_date is None:
        return None
    parsed = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int((parsed + timedelta(days=1)).timestamp() * 1000)


def fetch_candles_for_diagnostics(
    config: HyperliquidConfig,
    *,
    end_ms: int | None = None,
) -> list[Candle]:
    provider = HyperliquidHistoricalProvider(config)
    if end_ms is None:
        return provider.fetch_candles().candles

    start_ms, resolved_end_ms = compute_time_range_ms(
        interval=config.interval,
        lookback_bars=config.lookback_bars,
        now_ms=end_ms,
    )
    payload = provider._post_info(
        {
            "type": "candleSnapshot",
            "req": {
                "coin": config.coin,
                "interval": config.interval,
                "startTime": start_ms,
                "endTime": resolved_end_ms,
            },
        }
    )
    return provider._parse_candles(payload)


def build_strategy_diagnostics_rows(
    candles: list[Candle],
    *,
    config: StrategyConfig,
    account_balance: float = 10_000.0,
    min_warmup_bars: int = 150,
) -> list[dict[str, Any]]:
    if not candles:
        return []

    required_warmup_bars = _resolve_replay_warmup_bars(config, min_warmup_bars)
    if len(candles) < required_warmup_bars:
        return []

    rows: list[dict[str, Any]] = []
    for end_index in range(required_warmup_bars - 1, len(candles)):
        window = candles[: end_index + 1]
        strategy_result = run_strategy_cycle(
            candles=window,
            config=config,
            account_balance=account_balance,
        )
        diagnostics = _calculate_window_diagnostics(window, config)
        latest_candle = window[-1]
        trend_signal = strategy_result.trend_signal
        countertrend_signal = strategy_result.countertrend_signal

        rows.append(
            {
                "timestamp": latest_candle.timestamp.isoformat(),
                "open": latest_candle.open,
                "high": latest_candle.high,
                "low": latest_candle.low,
                "close": latest_candle.close,
                "analysis_bars": len(window),
                "required_warmup_bars": required_warmup_bars,
                "bollinger_period": config.bollinger_period,
                "bollinger_std_dev": config.bollinger_std_dev,
                "macd_fast_period": config.macd_fast_period,
                "macd_slow_period": config.macd_slow_period,
                "macd_signal_period": config.macd_signal_period,
                "inside_buffer_pct": config.inside_buffer_pct,
                "outside_buffer_pct": config.outside_buffer_pct,
                "outside_band_sweet_spot": config.outside_band_sweet_spot,
                "min_bandwidth_avg_period": config.min_bandwidth_avg_period,
                "min_bandwidth_ratio": config.min_bandwidth_ratio,
                "regime": diagnostics["latest_regime"],
                "bars_since_regime_start": diagnostics["bars_since_regime_start"],
                "bb_upper": diagnostics["bb_upper"],
                "bb_middle": diagnostics["bb_middle"],
                "bb_lower": diagnostics["bb_lower"],
                "relevant_half_bandwidth": diagnostics["relevant_half_bandwidth"],
                "average_relevant_half_bandwidth": diagnostics["average_relevant_half_bandwidth"],
                "bandwidth_ratio_value": diagnostics["bandwidth_ratio_value"],
                "bandwidth_ok": diagnostics["bandwidth_ok"],
                "close_inside_bands": diagnostics["close_inside_bands"],
                "candle_in_trend_direction": diagnostics["candle_in_trend_direction"],
                "inside_distance_actual": diagnostics["inside_distance_actual"],
                "inside_distance_required": diagnostics["inside_distance_required"],
                "inside_margin": diagnostics["inside_margin"],
                "outside_distance_actual": diagnostics["outside_distance_actual"],
                "outside_distance_required": diagnostics["outside_distance_required"],
                "outside_margin": diagnostics["outside_margin"],
                "close_deep_inside_bands": diagnostics["close_deep_inside_bands"],
                "close_deep_outside_bands": diagnostics["close_deep_outside_bands"],
                "trend_signal_valid": trend_signal.is_valid if trend_signal is not None else None,
                "trend_signal_type": trend_signal.signal_type.value if trend_signal is not None else None,
                "trend_reason": trend_signal.reason if trend_signal is not None else None,
                "countertrend_signal_valid": (
                    countertrend_signal.is_valid if countertrend_signal is not None else None
                ),
                "countertrend_signal_type": (
                    countertrend_signal.signal_type.value if countertrend_signal is not None else None
                ),
                "countertrend_reason": countertrend_signal.reason if countertrend_signal is not None else None,
                "decision_action": strategy_result.decision.action.value,
                "selected_signal_type": strategy_result.decision.selected_signal_type,
                "order_present": strategy_result.order is not None,
            }
        )

    return rows


def _default_output_base(config: HyperliquidConfig, end_date: str | None) -> Path:
    end_tag = end_date or "latest"
    return ARTIFACTS_DIR / f"strategy_diagnostics_{config.coin.lower()}_{config.interval}_{end_tag}"


def export_diagnostics_rows(
    rows: list[dict[str, Any]],
    *,
    output_json: Path,
    output_csv: Path,
) -> tuple[Path, Path]:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with output_csv.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    return output_json, output_csv


def main() -> None:
    args = _parse_args()
    if args.lookback_bars <= 0:
        raise ValueError("--lookback-bars must be greater than 0")
    if args.min_warmup_bars < 0:
        raise ValueError("--min-warmup-bars must be greater than or equal to 0")

    hyperliquid_config = _resolve_base_hyperliquid_config(args)
    end_ms = _resolve_end_ms(args.end_date)
    candles = fetch_candles_for_diagnostics(hyperliquid_config, end_ms=end_ms)
    strategy_config = build_strategy_config()
    rows = build_strategy_diagnostics_rows(
        candles,
        config=strategy_config,
        min_warmup_bars=args.min_warmup_bars,
    )

    output_base = _default_output_base(hyperliquid_config, args.end_date)
    output_json = Path(args.output_json) if args.output_json else output_base.with_suffix(".json")
    output_csv = Path(args.output_csv) if args.output_csv else output_base.with_suffix(".csv")
    json_path, csv_path = export_diagnostics_rows(rows, output_json=output_json, output_csv=output_csv)

    print("Strategy diagnostics export completed.")
    print(f"coin: {hyperliquid_config.coin}")
    print(f"interval: {hyperliquid_config.interval}")
    print(f"lookback_bars: {hyperliquid_config.lookback_bars}")
    print(f"rows: {len(rows)}")
    print(f"required_warmup_bars: {_resolve_replay_warmup_bars(strategy_config, args.min_warmup_bars)}")
    print(f"output_json: {json_path}")
    print(f"output_csv: {csv_path}")


if __name__ == "__main__":
    main()
