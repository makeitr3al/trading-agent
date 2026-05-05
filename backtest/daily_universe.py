from __future__ import annotations

import csv
import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from broker.asset_registry import AssetEntry, AssetRegistry
from config.hyperliquid_config import HyperliquidConfig
from config.strategy_config import StrategyConfig, build_strategy_config, min_strategy_candle_count
from data.providers.base import DataBatch
from data.providers.contract import validate_data_batch
from data.providers.hyperliquid_historical_provider import (
    HyperliquidHistoricalProvider,
    RequestsHyperliquidHttpClient,
    _INTERVAL_TO_MS,
)
from models.agent_state import AgentState
from models.candle import Candle
from models.trade import Trade, TradeDirection
from strategy.agent_cycle import run_agent_cycle

logger = logging.getLogger(__name__)

INTERVAL_1D = "1d"
INTERVAL_MS_1D = _INTERVAL_TO_MS[INTERVAL_1D]


def stable_shard_market(coin: str, shard_index: int, shard_total: int) -> bool:
    if shard_total <= 0:
        return True
    digest = hashlib.md5(coin.upper().encode("utf-8")).digest()
    val = int.from_bytes(digest[:8], "big", signed=False)
    return (val % shard_total) == shard_index


def merge_candles_sorted_values(chunks: Iterable[list[Candle]]) -> list[Candle]:
    by_ts: dict[datetime, Candle] = {}
    for chunk in chunks:
        for c in chunk:
            by_ts[c.timestamp] = c
    return [by_ts[k] for k in sorted(by_ts.keys())]


def _candles_to_json_rows(candles: list[Candle]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for c in candles:
        rows.append(
            {
                "t": int(c.timestamp.timestamp() * 1000),
                "o": c.open,
                "h": c.high,
                "l": c.low,
                "c": c.close,
            }
        )
    return rows


def _rows_to_candles(rows: list[dict[str, Any]], provider: HyperliquidHistoricalProvider) -> list[Candle]:
    return provider._parse_candles(rows)


def build_universe(registry: AssetRegistry, include_types: set[str]) -> list[AssetEntry]:
    registry.ensure_fresh()
    seen: set[str] = set()
    out: list[AssetEntry] = []
    for a in registry.list_all():
        if a.asset_type == "backend_coin":
            continue
        if a.asset_type not in include_types:
            continue
        key = a.propr_asset.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    out.sort(key=lambda x: x.propr_asset.upper())
    return out


@dataclass
class BacktestSimConfig:
    strategy: StrategyConfig
    initial_capital: float
    fee_roundtrip_bps: float = 0.0
    slippage_bps: float = 0.0
    compound: bool = True
    optimistic_fills: bool = False
    min_trades: int = 5
    min_trades_oos: int = 2
    oos_years: float | None = None
    max_dd_pct: float | None = None


@dataclass
class ExitTouch:
    price: float
    reason: str  # "sl" | "tp"


def touch_trade_sl_tp(
    trade: Trade | None,
    candle: Candle,
    *,
    optimistic: bool,
) -> ExitTouch | None:
    if trade is None or trade.quantity is None or trade.quantity <= 0:
        return None
    sl = trade.stop_loss
    tp = trade.take_profit

    if trade.direction == TradeDirection.LONG:
        hit_sl = candle.low <= sl
        hit_tp = False
        if tp is not None:
            tpf = float(tp)
            hit_tp = not math.isnan(tpf) and candle.high >= tpf
        if hit_sl and hit_tp:
            if optimistic:
                return ExitTouch(price=float(tp), reason="tp")
            return ExitTouch(price=float(sl), reason="sl")
        if hit_sl:
            return ExitTouch(price=float(sl), reason="sl")
        if hit_tp:
            return ExitTouch(price=float(tp), reason="tp")
        return None

    # SHORT
    hit_sl = candle.high >= sl
    hit_tp = False
    if tp is not None:
        tpf = float(tp)
        hit_tp = not math.isnan(tpf) and candle.low <= tpf
    if hit_sl and hit_tp:
        if optimistic:
            return ExitTouch(price=float(tp), reason="tp")
        return ExitTouch(price=float(sl), reason="sl")
    if hit_sl:
        return ExitTouch(price=float(sl), reason="sl")
    if hit_tp:
        return ExitTouch(price=float(tp), reason="tp")
    return None


def _apply_slippage_to_entry(direction: TradeDirection, price: float, slip_bps: float) -> float:
    s = slip_bps / 10_000.0
    if direction == TradeDirection.LONG:
        return price * (1.0 + s)
    return price * (1.0 - s)


def _apply_slippage_to_exit(direction: TradeDirection, price: float, slip_bps: float) -> float:
    s = slip_bps / 10_000.0
    if direction == TradeDirection.LONG:
        return price * (1.0 - s)
    return price * (1.0 + s)


def realize_pnl_for_closed_trade(
    trade: Trade,
    exit_price_raw: float,
    *,
    fee_roundtrip_bps: float,
    slippage_bps: float,
) -> dict[str, Any]:
    qty = float(trade.quantity or 0.0)
    if qty <= 0:
        return {
            "gross_pnl": 0.0,
            "fees": 0.0,
            "slippage_cost": 0.0,
            "net_pnl": 0.0,
            "entry_eff": float(trade.entry),
            "exit_eff": exit_price_raw,
        }

    entry_eff = _apply_slippage_to_entry(trade.direction, float(trade.entry), slippage_bps)
    exit_eff = _apply_slippage_to_exit(trade.direction, float(exit_price_raw), slippage_bps)

    if trade.direction == TradeDirection.LONG:
        gross = (exit_eff - entry_eff) * qty
    else:
        gross = (entry_eff - exit_eff) * qty

    notional_entry = abs(entry_eff * qty)
    notional_exit = abs(exit_eff * qty)
    half = (fee_roundtrip_bps / 10_000.0) / 2.0
    fees = notional_entry * half + notional_exit * half

    slip_cost = abs((float(trade.entry) - entry_eff) * qty) + abs((float(exit_price_raw) - exit_eff) * qty)

    net = gross - fees
    return {
        "gross_pnl": gross,
        "fees": fees,
        "slippage_cost": slip_cost,
        "net_pnl": net,
        "entry_eff": entry_eff,
        "exit_eff": exit_eff,
    }


@dataclass
class TradeRecord:
    market: str
    entry_ts: str
    entry_price: float
    exit_ts: str
    exit_price: float
    exit_reason: str
    qty: float
    direction: str
    trade_type: str
    gross_pnl: float
    fees: float
    slippage_cost: float
    net_pnl: float


def simulate_market_daily(
    candles: list[Candle],
    *,
    market: str,
    cfg: BacktestSimConfig,
) -> dict[str, Any]:
    min_need = min_strategy_candle_count(cfg.strategy)
    if len(candles) < min_need:
        return {
            "market": market,
            "skipped_reason": "insufficient_history",
            "n_bars": len(candles),
            "start_ts": candles[0].timestamp.isoformat() if candles else "",
            "end_ts": candles[-1].timestamp.isoformat() if candles else "",
            "n_trades": 0,
            "win_rate": 0.0,
            "gross_pnl": 0.0,
            "fees_total": 0.0,
            "slippage_total": 0.0,
            "net_pnl": 0.0,
            "return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "longest_dd_bars": 0,
            "profitable": False,
            "profitable_oos": None,
            "oos_net_pnl": None,
            "oos_n_trades": 0,
            "exit_reason_distribution": {},
            "trades": [],
        }

    state = AgentState()
    equity = float(cfg.initial_capital)
    initial = float(cfg.initial_capital)
    peak = equity
    max_dd_pct = 0.0
    dd_run_bars = 0
    longest_dd_bars = 0

    trades_out: list[TradeRecord] = []
    gross_sum = 0.0
    fees_sum = 0.0
    slip_sum = 0.0
    exit_hist: dict[str, int] = {}

    def _bump_dd() -> None:
        nonlocal peak, max_dd_pct, dd_run_bars, longest_dd_bars
        if equity >= peak:
            peak = equity
            dd_run_bars = 0
        else:
            dd = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
            max_dd_pct = max(max_dd_pct, dd)
            dd_run_bars += 1
            longest_dd_bars = max(longest_dd_bars, dd_run_bars)

    for i in range(min_need - 1, len(candles)):
        candles_i = candles[: i + 1]
        bar = candles_i[-1]
        now = bar.timestamp + timedelta(days=1)
        pre_trade = state.active_trade
        exit_event: ExitTouch | None = None

        if pre_trade is not None:
            exit_event = touch_trade_sl_tp(pre_trade, bar, optimistic=cfg.optimistic_fills)
            if exit_event is not None:
                r = realize_pnl_for_closed_trade(
                    pre_trade,
                    exit_event.price,
                    fee_roundtrip_bps=cfg.fee_roundtrip_bps,
                    slippage_bps=cfg.slippage_bps,
                )
                equity += float(r["net_pnl"])
                gross_sum += float(r["gross_pnl"])
                fees_sum += float(r["fees"])
                slip_sum += float(r["slippage_cost"])
                reason = f"intrabar_{exit_event.reason}"
                exit_hist[reason] = exit_hist.get(reason, 0) + 1
                trades_out.append(
                    TradeRecord(
                        market=market,
                        entry_ts=pre_trade.opened_at or "",
                        entry_price=float(pre_trade.entry),
                        exit_ts=bar.timestamp.isoformat(),
                        exit_price=float(exit_event.price),
                        exit_reason=reason,
                        qty=float(pre_trade.quantity or 0.0),
                        direction=pre_trade.direction.value,
                        trade_type=pre_trade.trade_type.value,
                        gross_pnl=float(r["gross_pnl"]),
                        fees=float(r["fees"]),
                        slippage_cost=float(r["slippage_cost"]),
                        net_pnl=float(r["net_pnl"]),
                    )
                )
                state = state.model_copy(update={"active_trade": None, "pending_order": None})

        balance_for_cycle = equity if cfg.compound else initial
        result, state = run_agent_cycle(
            candles=candles_i,
            config=cfg.strategy,
            account_balance=balance_for_cycle,
            state=state,
            now=now,
        )

        if pre_trade is not None and exit_event is None and state.active_trade is None:
            r = realize_pnl_for_closed_trade(
                pre_trade,
                float(bar.close),
                fee_roundtrip_bps=cfg.fee_roundtrip_bps,
                slippage_bps=cfg.slippage_bps,
            )
            equity += float(r["net_pnl"])
            gross_sum += float(r["gross_pnl"])
            fees_sum += float(r["fees"])
            slip_sum += float(r["slippage_cost"])
            action = result.decision.action.value
            exit_hist[f"strategy_{action}"] = exit_hist.get(f"strategy_{action}", 0) + 1
            trades_out.append(
                TradeRecord(
                    market=market,
                    entry_ts=pre_trade.opened_at or "",
                    entry_price=float(pre_trade.entry),
                    exit_ts=bar.timestamp.isoformat(),
                    exit_price=float(bar.close),
                    exit_reason=f"strategy_{action}",
                    qty=float(pre_trade.quantity or 0.0),
                    direction=pre_trade.direction.value,
                    trade_type=pre_trade.trade_type.value,
                    gross_pnl=float(r["gross_pnl"]),
                    fees=float(r["fees"]),
                    slippage_cost=float(r["slippage_cost"]),
                    net_pnl=float(r["net_pnl"]),
                )
            )

        at = state.active_trade
        if at is not None and at.opened_at and at.opened_at.startswith(bar.timestamp.isoformat()[:19]):
            touch2 = touch_trade_sl_tp(at, bar, optimistic=cfg.optimistic_fills)
            if touch2 is not None:
                r = realize_pnl_for_closed_trade(
                    at,
                    touch2.price,
                    fee_roundtrip_bps=cfg.fee_roundtrip_bps,
                    slippage_bps=cfg.slippage_bps,
                )
                equity += float(r["net_pnl"])
                gross_sum += float(r["gross_pnl"])
                fees_sum += float(r["fees"])
                slip_sum += float(r["slippage_cost"])
                reason = f"samebar_{touch2.reason}"
                exit_hist[reason] = exit_hist.get(reason, 0) + 1
                trades_out.append(
                    TradeRecord(
                        market=market,
                        entry_ts=at.opened_at or "",
                        entry_price=float(at.entry),
                        exit_ts=bar.timestamp.isoformat(),
                        exit_price=float(touch2.price),
                        exit_reason=reason,
                        qty=float(at.quantity or 0.0),
                        direction=at.direction.value,
                        trade_type=at.trade_type.value,
                        gross_pnl=float(r["gross_pnl"]),
                        fees=float(r["fees"]),
                        slippage_cost=float(r["slippage_cost"]),
                        net_pnl=float(r["net_pnl"]),
                    )
                )
                state = state.model_copy(update={"active_trade": None, "pending_order": None})

        _bump_dd()

    n_trades = len(trades_out)
    net_pnl = equity - initial
    ret_pct = (net_pnl / initial) * 100.0 if initial else 0.0
    winning = sum(1 for t in trades_out if t.net_pnl > 0.0)
    win_rate = (winning / n_trades) * 100.0 if n_trades else 0.0

    oos_net = None
    oos_n = 0
    profitable_oos = None
    if cfg.oos_years is not None and cfg.oos_years > 0 and candles:
        end_ts = candles[-1].timestamp
        cutoff = end_ts - timedelta(days=int(cfg.oos_years * 365.25))

        def _parse_exit_ts(ts: str) -> datetime:
            t = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(t)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)

        cutoff_utc = cutoff if cutoff.tzinfo else cutoff.replace(tzinfo=timezone.utc)
        oos_trades = [t for t in trades_out if _parse_exit_ts(t.exit_ts) >= cutoff_utc]
        oos_n = len(oos_trades)
        oos_net = sum(t.net_pnl for t in oos_trades)
        profitable_oos = bool(oos_net > 0 and oos_n >= cfg.min_trades_oos)

    profitable = bool(
        net_pnl > 0
        and n_trades >= cfg.min_trades
        and (cfg.max_dd_pct is None or max_dd_pct <= cfg.max_dd_pct)
    )

    return {
        "market": market,
        "skipped_reason": "",
        "n_bars": len(candles),
        "start_ts": candles[0].timestamp.isoformat(),
        "end_ts": candles[-1].timestamp.isoformat(),
        "n_trades": n_trades,
        "win_rate": win_rate,
        "gross_pnl": gross_sum,
        "fees_total": fees_sum,
        "slippage_total": slip_sum,
        "net_pnl": net_pnl,
        "return_pct": ret_pct,
        "max_drawdown_pct": max_dd_pct,
        "longest_dd_bars": longest_dd_bars,
        "profitable": profitable,
        "profitable_oos": profitable_oos,
        "oos_net_pnl": oos_net,
        "oos_n_trades": oos_n,
        "exit_reason_distribution": exit_hist,
        "trades": trades_out,
    }


def fetch_merged_daily_candles(
    coin: str,
    *,
    years: float,
    end_ms: int,
    cache_root: Path,
    refresh_data: bool,
    sleep_s: float,
    http_client: RequestsHyperliquidHttpClient | None = None,
) -> list[Candle]:
    """Year-window chunked fetch with per-window JSON cache."""
    interval_ms = INTERVAL_MS_1D
    bars_target = int(years * 365 + 30)
    start_ms = end_ms - bars_target * interval_ms
    chunk_ms = 365 * interval_ms

    cfg = HyperliquidConfig(coin=coin, interval=INTERVAL_1D, lookback_bars=1)
    provider = HyperliquidHistoricalProvider(cfg, http_client=http_client or RequestsHyperliquidHttpClient())

    safe = coin.replace(":", "_").replace("/", "_")
    merged_path = cache_root / safe / f"merged_1d_{start_ms}_{end_ms}.json"
    if merged_path.exists() and not refresh_data:
        raw = json.loads(merged_path.read_text(encoding="utf-8"))
        if not raw:
            return []
        merged = _rows_to_candles(raw, provider)
        if merged:
            validate_data_batch(DataBatch(candles=merged, symbol=coin, source_name="cache"))
        return merged

    cache_root.mkdir(parents=True, exist_ok=True)
    (cache_root / safe).mkdir(parents=True, exist_ok=True)

    chunks: list[list[Candle]] = []
    cur_end = end_ms
    while cur_end > start_ms:
        w_start = max(start_ms, cur_end - chunk_ms)
        wpath = cache_root / safe / f"win_{w_start}_{cur_end}.json"
        if wpath.exists() and not refresh_data:
            raw = json.loads(wpath.read_text(encoding="utf-8"))
            part = _rows_to_candles(raw, provider) if raw else []
        else:
            time.sleep(sleep_s)
            batch = provider.fetch_candles_between(w_start, cur_end)
            part = list(batch.candles)
            wpath.write_text(
                json.dumps(_candles_to_json_rows(part), ensure_ascii=False),
                encoding="utf-8",
            )
        if part:
            chunks.append(part)
        cur_end = w_start

    merged = merge_candles_sorted_values(chunks)
    if merged:
        validate_data_batch(DataBatch(candles=merged, symbol=coin, source_name="hyperliquid_historical_merged"))
    merged_path.parent.mkdir(parents=True, exist_ok=True)
    merged_path.write_text(json.dumps(_candles_to_json_rows(merged), ensure_ascii=False), encoding="utf-8")
    return merged


def write_trade_csv(path: Path, rows: list[TradeRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "market",
                "entry_ts",
                "entry_price",
                "exit_ts",
                "exit_price",
                "exit_reason",
                "qty",
                "direction",
                "trade_type",
                "gross_pnl",
                "fees",
                "slippage_cost",
                "net_pnl",
            ],
        )
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "market": r.market,
                    "entry_ts": r.entry_ts,
                    "entry_price": r.entry_price,
                    "exit_ts": r.exit_ts,
                    "exit_price": r.exit_price,
                    "exit_reason": r.exit_reason,
                    "qty": r.qty,
                    "direction": r.direction,
                    "trade_type": r.trade_type,
                    "gross_pnl": r.gross_pnl,
                    "fees": r.fees,
                    "slippage_cost": r.slippage_cost,
                    "net_pnl": r.net_pnl,
                }
            )
