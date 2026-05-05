from __future__ import annotations

from models.candle import Candle
from models.order import Order, OrderType


def is_order_trigger_touched(order: Order, candle: Candle) -> bool:
    """Return True when ``candle`` would trigger a resting order.

    Notes:
    - This is *bar-based* trigger semantics, shared by backtest and live-cycle logic.
    - Live trigger polling relies on the provider's last candle high/low being updated intrabar.
    """
    if order.order_type == OrderType.BUY_STOP:
        return candle.high >= order.entry
    if order.order_type == OrderType.SELL_STOP:
        return candle.low <= order.entry
    if order.order_type == OrderType.BUY_LIMIT:
        return candle.low <= order.entry
    if order.order_type == OrderType.SELL_LIMIT:
        return candle.high >= order.entry
    return False


def is_stop_trigger_touched(order: Order, candle: Candle) -> bool:
    if order.order_type not in {OrderType.BUY_STOP, OrderType.SELL_STOP}:
        return False
    return is_order_trigger_touched(order, candle)


def mark_order_triggered(order: Order) -> Order:
    """Return a copy of ``order`` that clearly indicates it was locally triggered."""
    src = (order.signal_source or "").strip()
    next_src = f"{src}_triggered" if src else "triggered"
    return order.model_copy(update={"signal_source": next_src})

