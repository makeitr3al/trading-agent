from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decimal import Decimal

from app.trading_app import _apply_symbol_specific_position_size
from broker.order_service import ProprOrderService, build_order_submission_preview
from config.strategy_config import StrategyConfig
from models.order import Order, OrderType
from models.symbol_spec import SymbolSpec


def _btc_spec() -> SymbolSpec:
    return SymbolSpec(
        symbol="BTC/USDC",
        asset="BTC",
        base="BTC",
        quote="USDC",
        quantity_decimals=3,
        price_decimals=2,
        max_leverage=50,
        source_name="test",
    )


def test_apply_symbol_specific_position_size_aligns_with_order_submission_preview() -> None:
    """Post-resize Order.position_size must match the quantity string sent to Propr."""
    config = StrategyConfig(risk_per_trade_pct=0.01)
    order = Order(
        order_type=OrderType.BUY_STOP,
        entry=107.0,
        stop_loss=100.0,
        take_profit=120.0,
        position_size=1.0,
        signal_source="trend_long",
    )
    spec = _btc_spec()
    sized = _apply_symbol_specific_position_size(
        order=order,
        config=config,
        account_balance=10000.0,
        desired_leverage=1,
        symbol_spec=spec,
    )
    assert sized.position_size == 14.285

    preview = build_order_submission_preview(sized, "BTC/USDC", symbol_spec=spec)
    assert preview["quantity"] == format(Decimal(str(sized.position_size)), "f")


def test_build_order_submission_preview_quantity_rounds_to_spec_decimals() -> None:
    spec = SymbolSpec(
        symbol="ETH/USDC",
        asset="ETH",
        base="ETH",
        quote="USDC",
        quantity_decimals=2,
        price_decimals=2,
        max_leverage=25,
        source_name="test",
    )
    order = Order(
        order_type=OrderType.BUY_LIMIT,
        entry=2000.0,
        stop_loss=1990.0,
        take_profit=2020.0,
        position_size=3.456789,
        signal_source="countertrend_long",
    )
    preview = build_order_submission_preview(order, "ETH/USDC", symbol_spec=spec)
    assert preview["quantity"] == "3.45"


def test_submit_pending_order_uses_preview_quantity(monkeypatch) -> None:
    captured: dict = {}

    class FakeClient:
        def create_order(self, account_id: str, **kwargs):
            captured["kwargs"] = kwargs
            return {"status": 200, "data": {"id": "fake-order"}}

    service = ProprOrderService(FakeClient())
    spec = _btc_spec()
    order = Order(
        order_type=OrderType.SELL_LIMIT,
        entry=50000.0,
        stop_loss=50100.0,
        take_profit=49000.0,
        position_size=0.00123,
        signal_source="countertrend_short",
    )
    preview = build_order_submission_preview(order, "BTC/USDC", symbol_spec=spec)

    def fake_submit_preview(account_id: str, submission_preview: dict):
        captured["preview"] = submission_preview
        return {"status": 200, "data": {"id": "fake-order"}}

    monkeypatch.setattr(service, "submit_order_preview", fake_submit_preview)
    service.submit_pending_order("acct-1", order, "BTC/USDC", symbol_spec=spec)

    assert captured["preview"]["quantity"] == preview["quantity"]
    assert captured["preview"]["quantity"] == "0.001"
