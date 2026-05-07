from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from app.journal import append_multi_market_scan_failure_journal
from app.trading_app import MAX_OPEN_ORDER_TRADE_SLOTS, run_app_cycle
from broker.asset_registry import AssetRegistry
from broker.challenge_service import get_active_challenge_context
from broker.order_service import ProprOrderService
from broker.propr_client import ProprClient
from broker.state_sync import sync_agent_state_from_propr
from broker.symbol_service import HyperliquidSymbolService
from config.hyperliquid_config import HyperliquidConfig
from config.strategy_config import StrategyConfig, build_strategy_config
from data.providers import get_data_provider
from data.providers.base import DataBatch
from data.providers.golden_data_provider import _load_golden_scenario
from data.providers.hyperliquid_historical_provider import HyperliquidHistoricalProvider
from models.order import OrderType
from utils.env_loader import DataSourceSettings, MultiMarketScanSettings, load_hyperliquid_config_from_env
from utils.live_status import write_live_status_from_state


@dataclass(frozen=True)
class ScanContext:
    environment: str
    data_source_settings: DataSourceSettings
    scan_settings: MultiMarketScanSettings
    effective_allow_submit: bool
    client: ProprClient
    order_service: ProprOrderService
    symbol_service: HyperliquidSymbolService
    registry: AssetRegistry
    hyperliquid_base_config: HyperliquidConfig | None


@dataclass(frozen=True)
class MarketScanResult:
    symbol: str
    coin: str
    data_batch: DataBatch | None
    strategy_config: StrategyConfig | None
    live_buy_spread: float
    result: Any | None
    summary: dict[str, Any]


@dataclass(frozen=True)
class ArmedMarketEntry:
    symbol: str
    coin: str
    order_type: str
    entry: float
    stop_loss: float
    take_profit: float
    signal_source: str
    selected_signal_type: str | None
    scan_ts: str


def maybe_upgrade_to_hip3_market(asset_ticker: str, registry: AssetRegistry) -> str:
    """
    If a bare ticker (e.g. EUR) is actually a HIP-3 market (xyz:EUR), upgrade it.

    This avoids treating non-crypto-perp tickers as Hyperliquid perp coins during scan validation.
    """
    from utils.asset_normalizer import normalize_asset

    info = normalize_asset(asset_ticker)
    if info.is_hip3:
        return info.asset

    raw = (asset_ticker or "").strip()
    if not raw or "/" in raw or raw.lower().startswith("xyz:"):
        return info.asset

    candidate = f"xyz:{info.base}"
    if registry.is_available(candidate):
        return candidate
    return info.asset


def _guard_to_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return None


def best_signal_strength(result: Any) -> float:
    strategy_result = getattr(result, "strategy_result", None)
    if strategy_result is None:
        return float("-inf")

    strengths: list[float] = []
    for signal in [strategy_result.trend_signal, strategy_result.countertrend_signal]:
        if signal is None or not signal.is_valid:
            continue
        strengths.append(float(signal.signal_strength or 0.0))

    if not strengths:
        return float("-inf")
    return max(strengths)


def select_execution_candidates(scan_summaries: list[dict[str, Any]], available_slots: int) -> list[dict[str, Any]]:
    if available_slots <= 0:
        return []

    candidates = [
        item
        for item in scan_summaries
        if item.get("pending_order_present") and not item.get("skipped_reason") and not item.get("stop_pending_present")
    ]
    if len(candidates) <= available_slots:
        return candidates

    return sorted(
        candidates,
        key=lambda item: item.get("best_signal_strength", float("-inf")),
        reverse=True,
    )[:available_slots]


def failed_market_summary(symbol: str, coin: str, exc: Exception) -> dict[str, Any]:
    print(f"Market: {symbol} ({coin})")
    print(f"  scan_failed_class: {exc.__class__.__name__}")
    print(f"  scan_failed: {exc}")
    return {
        "symbol": symbol,
        "coin": coin,
        "decision_action": None,
        "selected_signal_type": None,
        "trend_signal_valid": None,
        "countertrend_signal_valid": None,
        "pending_order_present": False,
        "stop_pending_present": False,
        "active_trade_present": False,
        "skipped_reason": str(exc),
        "best_signal_strength": float("-inf"),
        "result": None,
    }


def _is_stop_pending(result: Any) -> bool:
    post_cycle_state = getattr(result, "post_cycle_state", None)
    pending = getattr(post_cycle_state, "pending_order", None) if post_cycle_state is not None else None
    order_type = getattr(pending, "order_type", None) if pending is not None else None
    return order_type in {OrderType.BUY_STOP, OrderType.SELL_STOP}


def print_market_summary(symbol: str, coin: str, result: Any, live_buy_spread: float) -> dict[str, Any]:
    strategy_result = getattr(result, "strategy_result", None)
    post_cycle_state = getattr(result, "post_cycle_state", None)

    decision_action = None
    selected_signal_type = None
    trend_signal_valid = None
    countertrend_signal_valid = None
    decision_detail = None
    if strategy_result is not None:
        decision_action = strategy_result.decision.action.value
        selected_signal_type = strategy_result.decision.selected_signal_type
        decision_detail = getattr(strategy_result, "decision_detail", None)
        trend_signal_valid = (
            strategy_result.trend_signal.is_valid if strategy_result.trend_signal is not None else None
        )
        countertrend_signal_valid = (
            strategy_result.countertrend_signal.is_valid if strategy_result.countertrend_signal is not None else None
        )

    pending_order_present = False
    active_trade_present = False
    if post_cycle_state is not None:
        pending_order_present = post_cycle_state.pending_order is not None
        active_trade_present = post_cycle_state.active_trade is not None

    stop_pending_present = _is_stop_pending(result)
    best_strength = best_signal_strength(result)

    print(f"Market: {symbol} ({coin})")
    print(f"  skipped_reason: {getattr(result, 'skipped_reason', None)}")
    print(f"  live_buy_spread: {live_buy_spread}")
    print(f"  health_guard: {_guard_to_dict(getattr(result, 'health_guard_result', None))}")
    print(f"  risk_guard: {_guard_to_dict(getattr(result, 'risk_guard_result', None))}")
    print(f"  decision_action: {decision_action}")
    print(f"  selected_signal_type: {selected_signal_type}")
    print(f"  decision_detail: {decision_detail}")
    print(f"  trend_signal_valid: {trend_signal_valid}")
    print(f"  countertrend_signal_valid: {countertrend_signal_valid}")
    print(f"  pending_order_present: {pending_order_present}")
    print(f"  stop_pending_present: {stop_pending_present}")
    print(f"  active_trade_present: {active_trade_present}")
    print(f"  best_signal_strength: {best_strength}")
    print(f"  journal_entries: {len(getattr(result, 'journal_entries', []))}")
    print(f"  journal_path: {getattr(result, 'journal_path', None)}")

    return {
        "symbol": symbol,
        "coin": coin,
        "decision_action": decision_action,
        "selected_signal_type": selected_signal_type,
        "trend_signal_valid": trend_signal_valid,
        "countertrend_signal_valid": countertrend_signal_valid,
        "pending_order_present": pending_order_present,
        "stop_pending_present": stop_pending_present,
        "active_trade_present": active_trade_present,
        "skipped_reason": getattr(result, "skipped_reason", None),
        "best_signal_strength": best_strength,
        "result": result,
    }


def build_live_hyperliquid_config(base_config: HyperliquidConfig, coin: str) -> HyperliquidConfig:
    return HyperliquidConfig(
        base_url=base_config.base_url,
        info_path=base_config.info_path,
        coin=coin,
        interval=base_config.interval,
        lookback_bars=base_config.lookback_bars,
    )


def print_golden_expectations(scenario_name: str) -> None:
    scenario = _load_golden_scenario(scenario_name)
    print("Golden Expectations:")
    print(f"  expected_decision_action: {scenario.expected_decision_action}")
    print(f"  expected_order_present: {scenario.expected_order_present}")
    print(f"  expected_trend_signal_valid: {scenario.expected_trend_signal_valid}")
    print(f"  expected_countertrend_signal_valid: {scenario.expected_countertrend_signal_valid}")


def resolve_live_buy_spread(hyperliquid_config: HyperliquidConfig, require_for_execution: bool) -> float:
    try:
        return HyperliquidHistoricalProvider(hyperliquid_config).fetch_current_spread()
    except Exception as exc:
        if require_for_execution:
            raise ValueError(f"Failed to fetch live spread from Hyperliquid: {exc}") from exc
        print(f"  live spread unavailable ({exc}); using 0.0 for dry-run")
        return 0.0


def load_symbol_spec(symbol_service: HyperliquidSymbolService, symbol: str):
    try:
        return symbol_service.get_symbol_spec(symbol)
    except Exception as exc:
        print(f"  symbol spec unavailable for {symbol}: {exc}")
        return None


def build_data_batch_and_config(
    data_source: str,
    golden_scenario: str | None,
    hyperliquid_base_config: HyperliquidConfig | None,
    coin: str,
    require_for_execution: bool,
) -> tuple[DataBatch, StrategyConfig, float]:
    live_buy_spread = 0.0
    if data_source == "live":
        if hyperliquid_base_config is None:
            raise ValueError("Missing Hyperliquid base config for live data source")
        hyperliquid_config = build_live_hyperliquid_config(hyperliquid_base_config, coin)
        data_provider = get_data_provider("live", hyperliquid_config=hyperliquid_config)
        live_buy_spread = resolve_live_buy_spread(hyperliquid_config, require_for_execution=require_for_execution)
    else:
        data_provider = get_data_provider("golden", golden_scenario)

    data_batch = data_provider.get_data()
    strategy_overrides = data_batch.config.model_dump() if data_batch.config is not None else {}
    strategy_config = build_strategy_config(
        **{
            **strategy_overrides,
            "buy_spread": live_buy_spread,
        }
    )
    return data_batch, strategy_config, live_buy_spread


def persist_live_status(
    client: ProprClient,
    environment: str,
    symbol: str | None,
    *,
    last_error: str | None = None,
    challenge_id: str | None = None,
    challenge_attempt_id: str | None = None,
) -> None:
    from utils.live_status import build_live_status_payload, write_live_status

    try:
        challenge_context = get_active_challenge_context(
            client,
            attempt_id=challenge_attempt_id,
            challenge_id=challenge_id,
        )
        if challenge_context is None:
            write_live_status_from_state(
                environment=environment,
                state=None,
                source="poll",
                last_error=last_error or "no active challenge",
            )
            return

        state = sync_agent_state_from_propr(
            client,
            challenge_context.account_id,
            symbol=symbol,
        )

        balance_kwargs: dict[str, Any] = {}
        if challenge_context.account_balance is not None:
            ab = challenge_context.account_balance
            balance_kwargs = {
                "challenge_name": challenge_context.challenge_name,
                "challenge_id": challenge_context.challenge_id,
                "initial_balance": ab.initial_balance,
                "balance": ab.balance,
                "margin_balance": ab.margin_balance,
                "available_balance": ab.available_balance,
                "high_water_mark": ab.high_water_mark,
            }

        payload = build_live_status_payload(
            environment=environment,
            state=state,
            source="poll",
            last_error=last_error,
            **balance_kwargs,
        )
        write_live_status(payload)
    except Exception as exc:
        write_live_status_from_state(
            environment=environment,
            state=None,
            source="poll",
            last_error=last_error or str(exc),
        )


def build_scan_context(
    *,
    environment: str,
    data_source_settings: DataSourceSettings,
    scan_settings: MultiMarketScanSettings,
    propr_client: ProprClient,
    order_service: ProprOrderService,
    symbol_service: HyperliquidSymbolService,
    registry: AssetRegistry,
    hyperliquid_base_config: HyperliquidConfig | None = None,
) -> ScanContext:
    effective_allow_submit = scan_settings.allow_submit and data_source_settings.data_source == "live"
    effective_hl_base = hyperliquid_base_config
    if effective_hl_base is None and data_source_settings.data_source == "live":
        effective_hl_base = load_hyperliquid_config_from_env()
    return ScanContext(
        environment=environment,
        data_source_settings=data_source_settings,
        scan_settings=scan_settings,
        effective_allow_submit=effective_allow_submit,
        client=propr_client,
        order_service=order_service,
        symbol_service=symbol_service,
        registry=registry,
        hyperliquid_base_config=effective_hl_base,
    )


def scan_markets_once(
    context: ScanContext,
    *,
    executed_at: str | None = None,
    scan_cycle_phase: str = "dry_run",
    build_data_batch_and_config_fn=build_data_batch_and_config,
    run_app_cycle_fn=run_app_cycle,
) -> list[MarketScanResult]:
    from utils.asset_normalizer import hyperliquid_candle_coin, normalize_asset

    scan_executed_at = executed_at or datetime.now(timezone.utc).isoformat()
    results: list[MarketScanResult] = []

    for asset_ticker in context.scan_settings.assets:
        effective_ticker = maybe_upgrade_to_hip3_market(asset_ticker, context.registry)
        asset_info = normalize_asset(effective_ticker)
        symbol = asset_info.asset
        coin = hyperliquid_candle_coin(asset_info)
        print(f"Scanning asset={asset_ticker} coin={coin}")
        try:
            if context.data_source_settings.data_source == "live":
                context.registry.validate_scan_asset_for_hyperliquid_fetch(asset_info)

            data_batch, strategy_config, live_buy_spread = build_data_batch_and_config(
                # NOTE: injected to keep scripts/multi_market_scan.py monkeypatch tests stable.
                data_source=context.data_source_settings.data_source,
                golden_scenario=context.data_source_settings.golden_scenario,
                hyperliquid_base_config=context.hyperliquid_base_config,
                coin=coin,
                require_for_execution=False,
            )
            print(f"  source_name: {data_batch.source_name}")
            print(f"  live_buy_spread: {live_buy_spread}")

            result = run_app_cycle_fn(
                client=context.client,
                order_service=context.order_service,
                symbol=symbol,
                candles=data_batch.candles,
                config=strategy_config,
                account_balance=data_batch.account_balance or 10000.0,
                previous_state=data_batch.agent_state,
                require_healthy_core=context.scan_settings.require_healthy_core,
                allow_execution=False,
                desired_leverage=context.scan_settings.leverage,
                symbol_spec=None,
                data_source=context.data_source_settings.data_source,
                journal_path=context.scan_settings.journal_path,
                executed_at=scan_executed_at,
                challenge_id=context.scan_settings.challenge_id,
                challenge_attempt_id=context.scan_settings.challenge_attempt_id,
                journal_emit_pending_order=False,
                scan_effective_submit_allowed=context.effective_allow_submit,
                scan_cycle_phase=scan_cycle_phase,
            )

            summary = print_market_summary(symbol, coin, result, live_buy_spread)
            results.append(
                MarketScanResult(
                    symbol=symbol,
                    coin=coin,
                    data_batch=data_batch,
                    strategy_config=strategy_config,
                    live_buy_spread=live_buy_spread,
                    result=result,
                    summary=summary,
                )
            )
        except Exception as exc:
            summary = failed_market_summary(symbol, coin, exc)
            if context.scan_settings.journal_path:
                append_multi_market_scan_failure_journal(
                    context.scan_settings.journal_path,
                    symbol=symbol,
                    environment=context.environment,
                    executed_at=scan_executed_at,
                    error_message=str(exc),
                    scan_effective_submit_allowed=context.effective_allow_submit,
                )
            results.append(
                MarketScanResult(
                    symbol=symbol,
                    coin=coin,
                    data_batch=None,
                    strategy_config=None,
                    live_buy_spread=0.0,
                    result=None,
                    summary=summary,
                )
            )

    return results


def _compute_available_slots(reference_result: Any) -> int:
    synced_state = getattr(reference_result, "synced_state", None)
    currently_open_slots = 0
    if synced_state is not None:
        currently_open_slots = int(getattr(synced_state, "account_open_entry_orders_count", 0) or 0) + int(
            getattr(synced_state, "account_open_positions_count", 0) or 0
        )
    return max(0, MAX_OPEN_ORDER_TRADE_SLOTS - currently_open_slots)


def _iter_scan_summaries(scan_results: Iterable[MarketScanResult]) -> list[dict[str, Any]]:
    return [item.summary for item in scan_results]


def execute_candidates(
    context: ScanContext,
    scan_results: list[MarketScanResult],
    *,
    executed_at: str,
) -> None:
    if not context.effective_allow_submit:
        return

    scan_summaries = _iter_scan_summaries(scan_results)
    reference_result = next((row.result for row in scan_results if row.result is not None), None)
    if reference_result is None:
        return

    available_slots = _compute_available_slots(reference_result)
    print(f"Execution slots available: {available_slots}")
    if available_slots <= 0:
        print("No execution slots available. Skipping submits.")
        return

    selected_candidates = select_execution_candidates(scan_summaries, available_slots)
    if not selected_candidates:
        print("No executable signal candidates found.")
        return

    print("Executing markets:")
    for candidate in selected_candidates:
        print(
            f"  {candidate['symbol']} ({candidate['coin']}): selected_signal_type={candidate['selected_signal_type']}, "
            f"best_signal_strength={candidate['best_signal_strength']}"
        )

    contexts_by_symbol: dict[str, MarketScanResult] = {item.symbol: item for item in scan_results if item.data_batch}
    for candidate in selected_candidates:
        symbol = candidate["symbol"]
        market_context = contexts_by_symbol.get(symbol)
        if market_context is None or market_context.data_batch is None or market_context.strategy_config is None:
            continue

        symbol_spec = load_symbol_spec(context.symbol_service, symbol)
        execution_result = run_app_cycle(
            client=context.client,
            order_service=context.order_service,
            symbol=symbol,
            candles=market_context.data_batch.candles,
            config=market_context.strategy_config,
            account_balance=market_context.data_batch.account_balance or 10000.0,
            previous_state=market_context.data_batch.agent_state,
            require_healthy_core=context.scan_settings.require_healthy_core,
            allow_execution=True,
            desired_leverage=context.scan_settings.leverage,
            symbol_spec=symbol_spec,
            data_source=context.data_source_settings.data_source,
            journal_path=context.scan_settings.journal_path,
            executed_at=executed_at,
            challenge_id=context.scan_settings.challenge_id,
            challenge_attempt_id=context.scan_settings.challenge_attempt_id,
            scan_effective_submit_allowed=context.effective_allow_submit,
            scan_cycle_phase="execute",
        )
        print(
            f"Executed {symbol}: submitted={execution_result.submitted_order}, replaced={execution_result.replaced_order}, "
            f"skipped_reason={execution_result.skipped_reason}"
        )


def extract_armed_stop_markets(
    scan_results: list[MarketScanResult],
    *,
    scan_ts: str,
) -> list[ArmedMarketEntry]:
    armed: list[ArmedMarketEntry] = []
    for row in scan_results:
        result = row.result
        if result is None:
            continue
        post_cycle_state = getattr(result, "post_cycle_state", None)
        pending = getattr(post_cycle_state, "pending_order", None) if post_cycle_state is not None else None
        if pending is None:
            continue
        order_type = getattr(pending, "order_type", None)
        if order_type not in {OrderType.BUY_STOP, OrderType.SELL_STOP}:
            continue
        armed.append(
            ArmedMarketEntry(
                symbol=row.symbol,
                coin=row.coin,
                order_type=str(order_type),
                entry=float(getattr(pending, "entry")),
                stop_loss=float(getattr(pending, "stop_loss")),
                take_profit=float(getattr(pending, "take_profit")),
                signal_source=str(getattr(pending, "signal_source", "")),
                selected_signal_type=row.summary.get("selected_signal_type"),
                scan_ts=scan_ts,
            )
        )
    return armed

