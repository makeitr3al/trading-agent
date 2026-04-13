"""Shared fakes and factories for ``run_app_cycle`` / ``AppCycleResult`` tests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from models.candle import Candle
from models.decision import DecisionAction, DecisionResult
from models.order import Order, OrderType
from models.propr_challenge import ActiveChallengeContext, ProprChallengeAttempt
from models.runner_result import StrategyRunResult
from models.trade import Trade, TradeDirection, TradeType


class FakeConfig:
    def __init__(self, environment: str = "prod") -> None:
        self.environment = environment


class FakeClient:
    def __init__(self, environment: str = "prod") -> None:
        self.config = FakeConfig(environment)


class FakeOrderService:
    pass


def make_candles() -> list[Candle]:
    return [
        Candle(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
        )
    ]


def make_challenge_context(
    status: str = "active",
    failure_reason: str | None = None,
    max_drawdown: float | None = None,
) -> ActiveChallengeContext:
    attempt = ProprChallengeAttempt(
        attempt_id="attempt-1",
        account_id="account-1",
        status=status,
        failure_reason=failure_reason,
        max_drawdown=max_drawdown,
    )
    return ActiveChallengeContext(attempt=attempt, account_id="account-1")


def make_order() -> Order:
    return Order(
        order_type=OrderType.BUY_STOP,
        entry=110.0,
        stop_loss=100.0,
        take_profit=130.0,
        position_size=10.0,
        signal_source="trend_long",
    )


def make_strategy_result(order: Order | None = None, close_active_trade: bool = False) -> StrategyRunResult:
    return StrategyRunResult(
        trend_signal=None,
        countertrend_signal=None,
        decision=DecisionResult(action=DecisionAction.NO_ACTION, reason="test"),
        order=order,
        updated_trade=None,
        close_active_trade=close_active_trade,
    )


def make_trade() -> Trade:
    return Trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        quantity=0.5,
        position_id="position-1",
    )


def make_symbol_spec():
    from models.symbol_spec import SymbolSpec

    return SymbolSpec(
        symbol="BTC/USDC",
        asset="BTC",
        base="BTC",
        quote="USDC",
        quantity_decimals=3,
        price_decimals=None,
        max_leverage=5,
        source_name="test",
    )
