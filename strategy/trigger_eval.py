from __future__ import annotations

from decimal import Decimal

from models.candle import Candle
from models.order import Order, OrderType


def is_order_trigger_touched(order: Order, candle: Candle) -> bool:
    """Return True when ``candle`` would trigger a resting order.

    Notes:
    - This is *bar-based* trigger semantics, shared by backtest and live-cycle logic.
    - Live trigger polling (``TREND_STOP_TRIGGER_MODE=last_candle``) relies on the
      provider's last candle high/low being updated intrabar.
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


def _as_decimal(value: Decimal | float | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def is_stop_trigger_touched_by_trade(
    order: Order,
    trade_price: Decimal | float | int | str,
) -> bool:
    """Return True when a Hyperliquid last-trade print would fill a stop entry."""
    if order.order_type not in {OrderType.BUY_STOP, OrderType.SELL_STOP}:
        return False
    px = _as_decimal(trade_price)
    entry = _as_decimal(order.entry)
    if order.order_type == OrderType.BUY_STOP:
        return px >= entry
    return px <= entry


def stop_gap_excursion_ratio(
    order: Order,
    trade_price: Decimal | float | int | str,
) -> Decimal:
    """How far past ``order.entry`` the print is, as a fraction of |entry−SL|."""
    if order.order_type not in {OrderType.BUY_STOP, OrderType.SELL_STOP}:
        return Decimal("0")
    px = _as_decimal(trade_price)
    entry = _as_decimal(order.entry)
    stop_loss = _as_decimal(order.stop_loss)
    risk = abs(entry - stop_loss)
    if risk == 0:
        return Decimal("0")
    if order.order_type == OrderType.BUY_STOP:
        overshoot = px - entry
    else:
        overshoot = entry - px
    if overshoot <= 0:
        return Decimal("0")
    return overshoot / risk


def is_stop_gap_exceeded(
    order: Order,
    trade_price: Decimal | float | int | str,
    max_ratio: float | Decimal,
) -> bool:
    """True when the print is already past entry by more than ``max_ratio`` of risk."""
    return stop_gap_excursion_ratio(order, trade_price) > _as_decimal(max_ratio)


def mark_order_triggered(order: Order) -> Order:
    """Return a copy of ``order`` that clearly indicates it was locally triggered."""
    src = (order.signal_source or "").strip()
    next_src = f"{src}_triggered" if src else "triggered"
    return order.model_copy(update={"signal_source": next_src})
