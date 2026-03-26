from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.decision import DecisionAction, DecisionResult
from models.order import OrderType
from models.signal import SignalState, SignalType
from strategy.order_manager import build_order_from_decision


def _make_decision(action: DecisionAction) -> DecisionResult:
    return DecisionResult(action=action, reason="test")


def _make_signal(
    signal_type: SignalType,
    is_valid: bool = True,
    entry: float | None = 110.0,
    stop_loss: float | None = 100.0,
    take_profit: float | None = 130.0,
) -> SignalState:
    return SignalState(
        signal_type=signal_type,
        is_valid=is_valid,
        reason="test signal",
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )


def test_build_order_from_decision_no_action_returns_none() -> None:
    order = build_order_from_decision(
        decision=_make_decision(DecisionAction.NO_ACTION),
        trend_signal=None,
        countertrend_signal=None,
        current_price=110.0,
        account_balance=10000.0,
        risk_per_trade_pct=0.01,
    )

    assert order is None


def test_build_order_from_decision_prepare_trend_long_order() -> None:
    trend_signal = _make_signal(
        SignalType.TREND_LONG,
        entry=110.0,
        stop_loss=100.0,
        take_profit=130.0,
    )

    order = build_order_from_decision(
        decision=_make_decision(DecisionAction.PREPARE_TREND_ORDER),
        trend_signal=trend_signal,
        countertrend_signal=None,
        current_price=105.0,
        account_balance=10000.0,
        risk_per_trade_pct=0.01,
    )

    assert order is not None
    assert order.order_type == OrderType.BUY_STOP
    assert order.signal_source == "trend_long"
    assert order.position_size == pytest.approx(10.0)


def test_build_order_from_decision_prepare_trend_short_order() -> None:
    trend_signal = _make_signal(
        SignalType.TREND_SHORT,
        entry=90.0,
        stop_loss=100.0,
        take_profit=70.0,
    )

    order = build_order_from_decision(
        decision=_make_decision(DecisionAction.PREPARE_TREND_ORDER),
        trend_signal=trend_signal,
        countertrend_signal=None,
        current_price=95.0,
        account_balance=10000.0,
        risk_per_trade_pct=0.01,
    )

    assert order is not None
    assert order.order_type == OrderType.SELL_STOP
    assert order.position_size == pytest.approx(10.0)


def test_build_order_from_decision_prepare_countertrend_short_as_sell_limit() -> None:
    countertrend_signal = _make_signal(
        SignalType.COUNTERTREND_SHORT,
        entry=110.0,
        stop_loss=120.0,
        take_profit=100.0,
    )

    order = build_order_from_decision(
        decision=_make_decision(DecisionAction.PREPARE_COUNTERTREND_ORDER),
        trend_signal=None,
        countertrend_signal=countertrend_signal,
        current_price=111.0,
        account_balance=10000.0,
        risk_per_trade_pct=0.01,
    )

    assert order is not None
    assert order.order_type == OrderType.SELL_LIMIT
    assert order.signal_source == "countertrend_short"
    assert order.position_size == pytest.approx(10.0)


def test_build_order_from_decision_prepare_countertrend_short_as_sell_stop() -> None:
    countertrend_signal = _make_signal(
        SignalType.COUNTERTREND_SHORT,
        entry=110.0,
        stop_loss=120.0,
        take_profit=100.0,
    )

    order = build_order_from_decision(
        decision=_make_decision(DecisionAction.PREPARE_COUNTERTREND_ORDER),
        trend_signal=None,
        countertrend_signal=countertrend_signal,
        current_price=109.0,
        account_balance=10000.0,
        risk_per_trade_pct=0.01,
    )

    assert order is not None
    assert order.order_type == OrderType.SELL_STOP


def test_build_order_from_decision_prepare_countertrend_long_as_buy_stop() -> None:
    countertrend_signal = _make_signal(
        SignalType.COUNTERTREND_LONG,
        entry=90.0,
        stop_loss=80.0,
        take_profit=100.0,
    )

    order = build_order_from_decision(
        decision=_make_decision(DecisionAction.PREPARE_COUNTERTREND_ORDER),
        trend_signal=None,
        countertrend_signal=countertrend_signal,
        current_price=89.0,
        account_balance=10000.0,
        risk_per_trade_pct=0.01,
    )

    assert order is not None
    assert order.order_type == OrderType.BUY_STOP


def test_build_order_from_decision_prepare_countertrend_long_as_buy_limit() -> None:
    countertrend_signal = _make_signal(
        SignalType.COUNTERTREND_LONG,
        entry=90.0,
        stop_loss=80.0,
        take_profit=100.0,
    )

    order = build_order_from_decision(
        decision=_make_decision(DecisionAction.PREPARE_COUNTERTREND_ORDER),
        trend_signal=None,
        countertrend_signal=countertrend_signal,
        current_price=91.0,
        account_balance=10000.0,
        risk_per_trade_pct=0.01,
    )

    assert order is not None
    assert order.order_type == OrderType.BUY_LIMIT


def test_build_order_from_decision_close_trend_and_prepare_countertrend_uses_countertrend_logic() -> None:
    countertrend_signal = _make_signal(
        SignalType.COUNTERTREND_SHORT,
        entry=110.0,
        stop_loss=120.0,
        take_profit=100.0,
    )

    order = build_order_from_decision(
        decision=_make_decision(DecisionAction.CLOSE_TREND_AND_PREPARE_COUNTERTREND),
        trend_signal=None,
        countertrend_signal=countertrend_signal,
        current_price=111.0,
        account_balance=10000.0,
        risk_per_trade_pct=0.01,
    )

    assert order is not None
    assert order.order_type == OrderType.SELL_LIMIT


def test_build_order_from_decision_keep_existing_trend_trade_returns_none() -> None:
    order = build_order_from_decision(
        decision=_make_decision(DecisionAction.KEEP_EXISTING_TREND_TRADE),
        trend_signal=_make_signal(SignalType.TREND_LONG),
        countertrend_signal=None,
        current_price=110.0,
        account_balance=10000.0,
        risk_per_trade_pct=0.01,
    )

    assert order is None


def test_build_order_from_decision_returns_none_if_used_signal_is_missing() -> None:
    order = build_order_from_decision(
        decision=_make_decision(DecisionAction.PREPARE_TREND_ORDER),
        trend_signal=None,
        countertrend_signal=None,
        current_price=110.0,
        account_balance=10000.0,
        risk_per_trade_pct=0.01,
    )

    assert order is None


def test_build_order_from_decision_returns_none_if_used_signal_is_invalid() -> None:
    countertrend_signal = _make_signal(SignalType.COUNTERTREND_SHORT, is_valid=False)

    order = build_order_from_decision(
        decision=_make_decision(DecisionAction.PREPARE_COUNTERTREND_ORDER),
        trend_signal=None,
        countertrend_signal=countertrend_signal,
        current_price=111.0,
        account_balance=10000.0,
        risk_per_trade_pct=0.01,
    )

    assert order is None


def test_build_order_from_decision_returns_none_if_price_field_is_missing() -> None:
    trend_signal = _make_signal(
        SignalType.TREND_LONG,
        entry=110.0,
        stop_loss=None,
        take_profit=130.0,
    )

    order = build_order_from_decision(
        decision=_make_decision(DecisionAction.PREPARE_TREND_ORDER),
        trend_signal=trend_signal,
        countertrend_signal=None,
        current_price=105.0,
        account_balance=10000.0,
        risk_per_trade_pct=0.01,
    )

    assert order is None


def test_build_order_from_decision_returns_none_if_risk_per_unit_is_zero() -> None:
    trend_signal = _make_signal(
        SignalType.TREND_LONG,
        entry=100.0,
        stop_loss=100.0,
        take_profit=120.0,
    )

    order = build_order_from_decision(
        decision=_make_decision(DecisionAction.PREPARE_TREND_ORDER),
        trend_signal=trend_signal,
        countertrend_signal=None,
        current_price=99.0,
        account_balance=10000.0,
        risk_per_trade_pct=0.01,
    )

    assert order is None
