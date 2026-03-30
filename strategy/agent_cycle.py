import pandas as pd

from config.strategy_config import StrategyConfig
from indicators.bollinger import compute_bollinger_bands
from indicators.macd import compute_macd
from models.agent_state import AgentState
from models.candle import Candle
from models.decision import DecisionAction, DecisionResult
from models.order import Order, OrderType
from models.runner_result import StrategyRunResult
from models.signal import SignalState, SignalType
from models.trade import Trade, TradeDirection, TradeType
from strategy.order_manager import build_order_from_decision
from strategy.regime_detector import build_regime_states
from strategy.signal_rules import touches_middle_band
from strategy.strategy_runner import run_strategy_cycle

# TODO: Later manage pending-order validity across multiple days.
# TODO: Later add intrabar ordering when entry and SL/TP can both be touched.
# TODO: Later add partial fill handling.
# TODO: Later add support for multiple simultaneous orders.
# TODO: Later add real broker fill timing.
# TODO: Later add broker sync.
# TODO: Later implement aggressive reversal as a real trade state update.


def _is_order_filled(order: Order, candle: Candle) -> bool:
    if order.order_type == OrderType.BUY_STOP:
        return candle.high >= order.entry
    if order.order_type == OrderType.SELL_STOP:
        return candle.low <= order.entry
    if order.order_type == OrderType.BUY_LIMIT:
        return candle.low <= order.entry
    if order.order_type == OrderType.SELL_LIMIT:
        return candle.high >= order.entry
    return False


def _build_trade_from_filled_order(order: Order, fill_timestamp: str | None = None) -> Trade:
    if order.signal_source in ("trend_long", "trend_short"):
        trade_type = TradeType.TREND
    else:
        trade_type = TradeType.COUNTERTREND

    if order.signal_source in ("trend_long", "countertrend_long"):
        direction = TradeDirection.LONG
    else:
        direction = TradeDirection.SHORT

    return Trade(
        trade_type=trade_type,
        direction=direction,
        entry=order.entry,
        stop_loss=order.stop_loss,
        take_profit=order.take_profit,
        quantity=order.position_size,
        is_active=True,
        break_even_activated=False,
        opened_at=fill_timestamp,
    )


def _with_pending_order_created_at(order: Order | None, created_at: str) -> Order | None:
    if order is None:
        return None
    if order.created_at == created_at:
        return order
    return order.model_copy(update={"created_at": created_at})


def _is_countertrend_signal_consumed_in_regime(
    state: AgentState,
    last_regime: str | None,
    signal: SignalState | None,
) -> bool:
    if signal is None or not signal.is_valid or last_regime is None or state.last_regime != last_regime:
        return False

    if signal.signal_type == SignalType.COUNTERTREND_LONG:
        return state.countertrend_long_signal_consumed_in_regime

    if signal.signal_type == SignalType.COUNTERTREND_SHORT:
        return state.countertrend_short_signal_consumed_in_regime

    return False


def _is_signal_driven_action(action: DecisionAction) -> bool:
    return action in {
        DecisionAction.PREPARE_TREND_ORDER,
        DecisionAction.PREPARE_COUNTERTREND_ORDER,
        DecisionAction.CLOSE_TREND_AND_PREPARE_COUNTERTREND,
        DecisionAction.CLOSE_TREND_TRADE,
        DecisionAction.ADJUST_TREND_STOP_TO_LAST_CLOSE,
    }


def _invalidate_signal_for_middle_band_lock(signal: SignalState | None) -> SignalState | None:
    if signal is None:
        return None

    return signal.model_copy(
        update={
            "is_valid": False,
            "reason": "waiting for middle band retest",
        }
    )


def _apply_middle_band_retest_lock(
    result: StrategyRunResult,
    state: AgentState,
) -> StrategyRunResult:
    if not state.middle_band_retest_required:
        return result

    updates: dict[str, object] = {
        "trend_signal": _invalidate_signal_for_middle_band_lock(result.trend_signal),
        "countertrend_signal": _invalidate_signal_for_middle_band_lock(result.countertrend_signal),
    }

    if _is_signal_driven_action(result.decision.action):
        updates.update(
            {
                "decision": DecisionResult(
                    action=DecisionAction.NO_ACTION,
                    reason="waiting for middle band retest",
                    selected_signal_type=None,
                ),
                "order": None,
                "updated_trade": None,
                "close_active_trade": False,
            }
        )

    return result.model_copy(update=updates)


def _resolve_middle_band_retest_required(
    candles: list[Candle],
    config: StrategyConfig,
    previous_required: bool,
) -> bool:
    closes = pd.Series([candle.close for candle in candles], dtype=float)
    bollinger_df = compute_bollinger_bands(
        closes=closes,
        period=config.bollinger_period,
        std_dev=config.bollinger_std_dev,
    )
    latest_bollinger = bollinger_df.iloc[-1]
    bb_upper = latest_bollinger["bb_upper"]
    bb_middle = latest_bollinger["bb_middle"]
    bb_lower = latest_bollinger["bb_lower"]

    if pd.isna(bb_upper) or pd.isna(bb_middle) or pd.isna(bb_lower):
        return previous_required

    latest_candle = candles[-1]
    close_outside_bands = latest_candle.close > float(bb_upper) or latest_candle.close < float(bb_lower)
    if close_outside_bands:
        return True

    if touches_middle_band(
        high=latest_candle.high,
        low=latest_candle.low,
        bb_middle=float(bb_middle),
    ):
        return False

    return previous_required


def run_agent_cycle(
    candles: list[Candle],
    config: StrategyConfig,
    account_balance: float,
    state: AgentState,
) -> tuple[StrategyRunResult, AgentState]:
    old_pending_order = state.pending_order
    latest_candle = candles[-1]
    filled_trade = None
    working_active_trade = state.active_trade

    if old_pending_order is not None and _is_order_filled(old_pending_order, latest_candle):
        filled_trade = _build_trade_from_filled_order(old_pending_order, latest_candle.timestamp.isoformat())
        working_active_trade = filled_trade
        old_pending_order = None

    result = run_strategy_cycle(
        candles=candles,
        config=config,
        account_balance=account_balance,
        active_trade=working_active_trade,
    )
    result = _apply_middle_band_retest_lock(result=result, state=state)

    closes = pd.Series([candle.close for candle in candles], dtype=float)
    macd_df = compute_macd(
        closes=closes,
        fast_period=config.macd_fast_period,
        slow_period=config.macd_slow_period,
        signal_period=config.macd_signal_period,
    )
    regime_states = build_regime_states(macd_df)
    last_regime = regime_states[-1].regime.value if regime_states else None
    regime_changed = state.last_regime is not None and state.last_regime != last_regime
    current_price = float(closes.iloc[-1])
    middle_band_retest_required = _resolve_middle_band_retest_required(
        candles=candles,
        config=config,
        previous_required=state.middle_band_retest_required,
    )

    duplicate_trend_signal_blocked = (
        state.trend_signal_consumed_in_regime
        and state.last_regime is not None
        and state.last_regime == last_regime
        and result.decision.action == DecisionAction.PREPARE_TREND_ORDER
    )
    if duplicate_trend_signal_blocked:
        invalid_trend_signal = None
        if result.trend_signal is not None:
            invalid_trend_signal = result.trend_signal.model_copy(
                update={
                    "is_valid": False,
                    "reason": "trend regime consumed",
                }
            )
        result = result.model_copy(
            update={
                "decision": DecisionResult(
                    action=DecisionAction.NO_ACTION,
                    reason="trend signal already consumed in regime",
                    selected_signal_type=None,
                ),
                "order": None,
                "trend_signal": invalid_trend_signal,
            }
        )

    duplicate_countertrend_signal_blocked = _is_countertrend_signal_consumed_in_regime(
        state=state,
        last_regime=last_regime,
        signal=result.countertrend_signal,
    )
    if duplicate_countertrend_signal_blocked:
        invalid_countertrend_signal = None
        if result.countertrend_signal is not None:
            invalid_countertrend_signal = result.countertrend_signal.model_copy(
                update={
                    "is_valid": False,
                    "reason": "countertrend regime direction consumed",
                }
            )
        result = result.model_copy(
            update={
                "decision": DecisionResult(
                    action=DecisionAction.NO_ACTION,
                    reason="countertrend signal already consumed in regime direction",
                    selected_signal_type=None,
                ),
                "order": None,
                "countertrend_signal": invalid_countertrend_signal,
                "updated_trade": None,
                "close_active_trade": False,
            }
        )

    pending_order_created_at = latest_candle.timestamp.isoformat()

    if result.order is not None:
        pending_order = _with_pending_order_created_at(result.order, pending_order_created_at)
    elif (
        old_pending_order is not None
        and old_pending_order.signal_source
        in ("countertrend_long", "countertrend_short")
    ):
        pending_order = None
    elif (
        old_pending_order is not None
        and old_pending_order.signal_source in ("trend_long", "trend_short")
    ):
        if (
            result.trend_signal is not None
            and result.trend_signal.is_valid
            and result.trend_signal.signal_type.value.lower()
            == old_pending_order.signal_source
        ):
            pending_order = _with_pending_order_created_at(
                build_order_from_decision(
                    decision=DecisionResult(
                        action=DecisionAction.PREPARE_TREND_ORDER,
                        reason="refresh trend pending order",
                        selected_signal_type=result.trend_signal.signal_type.value,
                    ),
                    trend_signal=result.trend_signal,
                    countertrend_signal=result.countertrend_signal,
                    current_price=current_price,
                    account_balance=account_balance,
                    risk_per_trade_pct=config.risk_per_trade_pct,
                    buy_spread=config.buy_spread,
                ),
                pending_order_created_at,
            )
        else:
            pending_order = None
    else:
        pending_order = old_pending_order

    trend_signal_consumed_in_regime = (
        False if regime_changed else state.trend_signal_consumed_in_regime
    )
    countertrend_long_signal_consumed_in_regime = (
        False if regime_changed else state.countertrend_long_signal_consumed_in_regime
    )
    countertrend_short_signal_consumed_in_regime = (
        False if regime_changed else state.countertrend_short_signal_consumed_in_regime
    )
    if result.decision.action in {
        DecisionAction.PREPARE_TREND_ORDER,
        DecisionAction.CLOSE_TREND_TRADE,
        DecisionAction.ADJUST_TREND_STOP_TO_LAST_CLOSE,
    }:
        trend_signal_consumed_in_regime = True
    if result.countertrend_signal is not None and result.countertrend_signal.is_valid:
        if result.countertrend_signal.signal_type == SignalType.COUNTERTREND_LONG:
            countertrend_long_signal_consumed_in_regime = True
        elif result.countertrend_signal.signal_type == SignalType.COUNTERTREND_SHORT:
            countertrend_short_signal_consumed_in_regime = True

    active_trade = (
        None
        if result.close_active_trade
        else result.updated_trade
        if result.updated_trade is not None
        else filled_trade
        if filled_trade is not None
        else state.active_trade
    )

    new_state = state.model_copy(
        update={
            "active_trade": active_trade,
            "pending_order": pending_order,
            "last_decision_action": result.decision.action.value,
            "last_signal_type": result.decision.selected_signal_type
            if result.decision.selected_signal_type is not None
            else None,
            "last_regime": last_regime,
            "middle_band_retest_required": middle_band_retest_required,
            "trend_signal_consumed_in_regime": trend_signal_consumed_in_regime,
            "countertrend_long_signal_consumed_in_regime": countertrend_long_signal_consumed_in_regime,
            "countertrend_short_signal_consumed_in_regime": countertrend_short_signal_consumed_in_regime,
            "last_cycle_timestamp": candles[-1].timestamp.isoformat(),
        }
    )

    result = result.model_copy(update={"filled_trade": filled_trade})

    return result, new_state

