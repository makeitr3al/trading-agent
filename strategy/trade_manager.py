from models.trade import Trade, TradeDirection, TradeType

# TODO: Later implement actual trade closing.
# TODO: Later add intrabar checks for TP or SL hits.
# TODO: Later add aggressive reversal handling from active trend to countertrend.


def _normalize_buy_spread(buy_spread: float) -> float:
    return max(0.0, float(buy_spread))


def _tighten_trend_stop_loss(active_trade: Trade, latest_bb_middle: float, buy_spread: float) -> float:
    if active_trade.direction == TradeDirection.LONG:
        target_stop_loss = latest_bb_middle + _normalize_buy_spread(buy_spread)
        return max(active_trade.stop_loss, target_stop_loss)

    target_stop_loss = latest_bb_middle
    return min(active_trade.stop_loss, target_stop_loss)


def _countertrend_take_profit_from_middle_band(active_trade: Trade, latest_bb_middle: float, buy_spread: float) -> float:
    if active_trade.direction == TradeDirection.LONG:
        return latest_bb_middle + _normalize_buy_spread(buy_spread)
    return latest_bb_middle


def tighten_trend_stop_to_last_close(active_trade: Trade, latest_close: float) -> Trade:
    if active_trade.direction == TradeDirection.LONG:
        new_stop_loss = max(active_trade.stop_loss, latest_close)
    else:
        new_stop_loss = min(active_trade.stop_loss, latest_close)
    return active_trade.model_copy(update={"stop_loss": new_stop_loss})


def tighten_trend_stop_to_signal_bar_close(active_trade: Trade, signal_bar_close: float) -> Trade:
    """Move trend stop toward signal-bar close (same tightening direction as last-close adjust)."""
    if active_trade.direction == TradeDirection.LONG:
        new_stop_loss = max(active_trade.stop_loss, signal_bar_close)
    else:
        new_stop_loss = min(active_trade.stop_loss, signal_bar_close)
    return active_trade.model_copy(update={"stop_loss": new_stop_loss})


def update_active_trade(
    active_trade: Trade | None,
    latest_bb_middle: float,
    latest_close: float,
    buy_spread: float = 0.0,
) -> Trade | None:
    if active_trade is None:
        return None

    if active_trade.trade_type == TradeType.TREND:
        if active_trade.break_even_activated:
            return active_trade.model_copy(
                update={
                    "stop_loss": active_trade.entry,
                    "break_even_activated": True,
                }
            )

        if active_trade.direction == TradeDirection.LONG:
            initial_risk = active_trade.entry - active_trade.stop_loss
            if initial_risk <= 0:
                return active_trade

            profit = latest_close - active_trade.entry
            if profit >= initial_risk:
                return active_trade.model_copy(
                    update={
                        "stop_loss": active_trade.entry,
                        "break_even_activated": True,
                    }
                )

            return active_trade.model_copy(
                update={
                    "stop_loss": _tighten_trend_stop_loss(
                        active_trade=active_trade,
                        latest_bb_middle=latest_bb_middle,
                        buy_spread=buy_spread,
                    )
                }
            )

        initial_risk = active_trade.stop_loss - active_trade.entry
        if initial_risk <= 0:
            return active_trade

        profit = active_trade.entry - latest_close
        if profit >= initial_risk:
            return active_trade.model_copy(
                update={
                    "stop_loss": active_trade.entry,
                    "break_even_activated": True,
                }
            )

        return active_trade.model_copy(
            update={
                "stop_loss": _tighten_trend_stop_loss(
                    active_trade=active_trade,
                    latest_bb_middle=latest_bb_middle,
                    buy_spread=buy_spread,
                )
            }
        )

    return active_trade.model_copy(
        update={
            "take_profit": _countertrend_take_profit_from_middle_band(
                active_trade=active_trade,
                latest_bb_middle=latest_bb_middle,
                buy_spread=buy_spread,
            )
        }
    )

