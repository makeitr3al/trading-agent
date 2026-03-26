from models.trade import Trade, TradeType

# TODO: Later implement actual trade closing.
# TODO: Later add intrabar checks for TP or SL hits.
# TODO: Later add aggressive reversal handling from active trend to countertrend.


def update_active_trade(
    active_trade: Trade | None,
    latest_bb_middle: float,
    latest_close: float,
) -> Trade | None:
    if active_trade is None:
        return None

    if active_trade.trade_type == TradeType.TREND:
        if active_trade.break_even_activated:
            return active_trade.copy(
                update={
                    "stop_loss": active_trade.entry,
                    "break_even_activated": True,
                }
            )

        if active_trade.direction.value == "LONG":
            initial_risk = active_trade.entry - active_trade.stop_loss
            if initial_risk <= 0:
                return active_trade

            profit = latest_close - active_trade.entry
            if profit >= initial_risk:
                return active_trade.copy(
                    update={
                        "stop_loss": active_trade.entry,
                        "break_even_activated": True,
                    }
                )

            return active_trade.copy(update={"stop_loss": latest_bb_middle})

        initial_risk = active_trade.stop_loss - active_trade.entry
        if initial_risk <= 0:
            return active_trade

        profit = active_trade.entry - latest_close
        if profit >= initial_risk:
            return active_trade.copy(
                update={
                    "stop_loss": active_trade.entry,
                    "break_even_activated": True,
                }
            )

        return active_trade.copy(update={"stop_loss": latest_bb_middle})

    return active_trade.copy(update={"take_profit": latest_bb_middle})
