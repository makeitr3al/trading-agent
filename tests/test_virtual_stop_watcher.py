"""Virtual-stop helpers: trade touch, gap guard, bar time, state sync preserve."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.armed_stop_submit import (
    execute_armed_stop_market_bracket,
    max_gap_excursion_ratio,
    stable_intent_seed_for_armed_stop,
    trend_stop_trigger_mode,
)
from broker.asset_guard import AssetGuardResult
from broker.state_sync import build_agent_state_from_propr_data
from data.providers.hyperliquid_ws import HyperliquidTradesWatcher
from models.agent_state import AgentState
from models.candle import Candle
from models.order import Order, OrderType
from strategy.agent_cycle import run_agent_cycle
from strategy.trigger_eval import (
    is_stop_gap_exceeded,
    is_stop_trigger_touched_by_trade,
    stop_gap_excursion_ratio,
)
from utils.bar_time import floor_bar_open_utc, interval_to_seconds


def _buy_stop() -> Order:
    return Order(
        order_type=OrderType.BUY_STOP,
        entry=110.0,
        stop_loss=100.0,
        take_profit=130.0,
        position_size=1.0,
        signal_source="trend_long",
    )


def test_trade_print_touch_buy_and_sell() -> None:
    buy = _buy_stop()
    assert is_stop_trigger_touched_by_trade(buy, Decimal("110")) is True
    assert is_stop_trigger_touched_by_trade(buy, Decimal("109.99")) is False
    sell = buy.model_copy(update={"order_type": OrderType.SELL_STOP, "entry": 90.0, "stop_loss": 100.0})
    assert is_stop_trigger_touched_by_trade(sell, Decimal("90")) is True
    assert is_stop_trigger_touched_by_trade(sell, Decimal("90.01")) is False


def test_gap_excursion_ratio_and_exceeded() -> None:
    order = _buy_stop()
    # risk = 10; print at 116 → overshoot 6 → ratio 0.6
    assert stop_gap_excursion_ratio(order, 116.0) == Decimal("0.6")
    assert is_stop_gap_exceeded(order, 116.0, 0.5) is True
    assert is_stop_gap_exceeded(order, 114.0, 0.5) is False


def test_floor_bar_open_utc_1h() -> None:
    dt = datetime(2026, 5, 5, 13, 42, tzinfo=timezone.utc)
    assert floor_bar_open_utc(dt, "1h") == datetime(2026, 5, 5, 13, 0, tzinfo=timezone.utc)
    assert interval_to_seconds("1d") == 86400


def test_state_sync_preserves_local_virtual_stop() -> None:
    previous = AgentState(
        pending_order=_buy_stop(),
        signal_lifecycle_id="life-1",
        last_regime="bullish",
    )
    state = build_agent_state_from_propr_data(
        orders_payload={"data": []},
        positions_payload={"data": []},
        previous_state=previous,
        symbol="BTC/USDC",
    )
    assert state.pending_order is not None
    assert state.pending_order.order_type == OrderType.BUY_STOP
    assert state.pending_order_id is None
    assert state.signal_lifecycle_id == "life-1"


def test_state_sync_clears_virtual_stop_when_broker_position_open() -> None:
    previous = AgentState(pending_order=_buy_stop())
    state = build_agent_state_from_propr_data(
        orders_payload={"data": []},
        positions_payload={
            "data": [
                {
                    "symbol": "BTC/USDC",
                    "status": "open",
                    "positionSide": "long",
                    "entryPrice": "100",
                    "stopLoss": "95",
                    "takeProfit": "110",
                    "quantity": "1",
                    "positionId": "pos-1",
                }
            ]
        },
        previous_state=previous,
        symbol="BTC/USDC",
    )
    assert state.pending_order is None
    assert state.has_open_broker_position_for_symbol is True


def test_stable_intent_seed_uses_lifecycle_not_clock() -> None:
    seed = stable_intent_seed_for_armed_stop(
        account_id="acc",
        symbol="BTC",
        signal_lifecycle_id="life-9",
        order=_buy_stop(),
    )
    assert seed is not None
    assert "life-9" in seed
    assert "2026" not in seed


def test_execute_armed_stop_gap_disarms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TREND_STOP_MAX_GAP_R_RATIO", "0.25")

    class _Svc:
        def submit_market_entry_bracket_with_exits(self, *_a, **_k):
            raise AssertionError("must not submit on gap")

    result = execute_armed_stop_market_bracket(
        client=object(),  # type: ignore[arg-type]
        order_service=_Svc(),  # type: ignore[arg-type]
        account_id="acc",
        symbol="BTC/USDC",
        order=_buy_stop(),
        synced_state=AgentState(pending_order=_buy_stop()),
        signal_lifecycle_id="life-1",
        account_balance=10_000.0,
        asset_guard_result=AssetGuardResult(
            allow_execution=True,
            reason=None,
            asset="BTC",
            desired_leverage=1,
            max_leverage=5,
        ),
        trigger_price=120.0,  # 1.0 R past entry
        skip_position_probe=True,
    )
    assert result.submitted is False
    assert result.disarmed is True
    assert result.skipped_reason is not None
    assert "gap" in result.skipped_reason


def test_execute_armed_stop_submits_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TREND_STOP_MAX_GAP_R_RATIO", "OFF")
    captured: dict[str, object] = {}

    class _Svc:
        def submit_market_entry_bracket_with_exits(self, account_id, order, symbol, **kwargs):
            captured["account_id"] = account_id
            captured["order"] = order
            captured["symbol"] = symbol
            captured["stable_intent_seed"] = kwargs.get("stable_intent_seed")
            return {"data": [{"orderId": "oid-1"}]}

    order = _buy_stop()
    result = execute_armed_stop_market_bracket(
        client=object(),  # type: ignore[arg-type]
        order_service=_Svc(),  # type: ignore[arg-type]
        account_id="acc",
        symbol="BTC/USDC",
        order=order,
        synced_state=AgentState(pending_order=order, signal_lifecycle_id="life-1"),
        signal_lifecycle_id="life-1",
        account_balance=10_000.0,
        asset_guard_result=AssetGuardResult(
            allow_execution=True,
            reason=None,
            asset="BTC",
            desired_leverage=1,
            max_leverage=5,
        ),
        trigger_price=110.0,
        skip_position_probe=True,
    )
    assert result.submitted is True
    assert result.pending_order_id == "oid-1"
    assert captured["stable_intent_seed"] is not None
    assert "life-1" in str(captured["stable_intent_seed"])
    assert str(getattr(captured["order"], "signal_source")).endswith("_triggered")


def test_run_agent_cycle_skips_local_fill_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from config.strategy_config import StrategyConfig
    from models.decision import DecisionAction, DecisionResult
    from models.runner_result import StrategyRunResult

    candles = [
        Candle(
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            open=100.0,
            high=120.0,
            low=99.0,
            close=100.0,
        )
    ]
    state = AgentState(pending_order=_buy_stop())

    def _fake_strategy(**_kwargs):
        return StrategyRunResult(
            trend_signal=None,
            countertrend_signal=None,
            decision=DecisionResult(action=DecisionAction.NO_ACTION, reason="test"),
            order=None,
            updated_trade=None,
            close_active_trade=False,
        )

    monkeypatch.setattr("strategy.agent_cycle.run_strategy_cycle", _fake_strategy)
    _result, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10_000.0,
        state=state,
        synthesize_local_fills=False,
    )
    assert new_state.active_trade is None


def test_hyperliquid_ws_parse_trade() -> None:
    tick = HyperliquidTradesWatcher._parse_trade(
        {"coin": "BTC", "px": "65000.5", "side": "B", "time": 1_700_000_000_000}
    )
    assert tick is not None
    assert tick.coin == "BTC"
    assert tick.price == Decimal("65000.5")


def test_trend_stop_trigger_mode_default_and_ws(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TREND_STOP_TRIGGER_MODE", raising=False)
    assert trend_stop_trigger_mode() == "last_candle"
    monkeypatch.setenv("TREND_STOP_TRIGGER_MODE", "ws")
    assert trend_stop_trigger_mode() == "ws"


def test_max_gap_ratio_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TREND_STOP_MAX_GAP_R_RATIO", raising=False)
    assert max_gap_excursion_ratio() == 0.5
    monkeypatch.setenv("TREND_STOP_MAX_GAP_R_RATIO", "OFF")
    assert max_gap_excursion_ratio() is None
