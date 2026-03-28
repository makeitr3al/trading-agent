from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.trade import Trade, TradeDirection, TradeType
from strategy.trade_manager import update_active_trade


def _make_trade(
    trade_type: TradeType,
    direction: TradeDirection,
    entry: float,
    stop_loss: float,
    take_profit: float,
    break_even_activated: bool = False,
) -> Trade:
    return Trade(
        trade_type=trade_type,
        direction=direction,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        break_even_activated=break_even_activated,
    )


def test_update_active_trade_returns_none_for_no_active_trade() -> None:
    updated_trade = update_active_trade(
        active_trade=None,
        latest_bb_middle=97.0,
        latest_close=102.0,
    )

    assert updated_trade is None


def test_trend_long_updates_stop_loss_to_latest_bb_middle_before_break_even() -> None:
    active_trade = _make_trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=95.0,
        take_profit=110.0,
    )

    updated_trade = update_active_trade(
        active_trade=active_trade,
        latest_bb_middle=97.0,
        latest_close=103.0,
    )

    assert updated_trade is not None
    assert updated_trade.stop_loss == 97.0
    assert updated_trade.break_even_activated is False
    assert updated_trade.take_profit == 110.0


def test_trend_long_stop_loss_only_tightens_and_never_widens() -> None:
    active_trade = _make_trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=98.0,
        take_profit=110.0,
    )

    updated_trade = update_active_trade(
        active_trade=active_trade,
        latest_bb_middle=96.0,
        latest_close=101.0,
    )

    assert updated_trade is not None
    assert updated_trade.stop_loss == 98.0


def test_trend_long_updates_stop_loss_with_buy_spread() -> None:
    active_trade = _make_trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=95.0,
        take_profit=110.0,
    )

    updated_trade = update_active_trade(
        active_trade=active_trade,
        latest_bb_middle=97.0,
        latest_close=103.0,
        buy_spread=1.5,
    )

    assert updated_trade is not None
    assert updated_trade.stop_loss == 98.5
    assert updated_trade.break_even_activated is False


def test_trend_long_activates_break_even_at_1r() -> None:
    active_trade = _make_trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=95.0,
        take_profit=110.0,
    )

    updated_trade = update_active_trade(
        active_trade=active_trade,
        latest_bb_middle=97.0,
        latest_close=105.0,
    )

    assert updated_trade is not None
    assert updated_trade.stop_loss == 100.0
    assert updated_trade.break_even_activated is True


def test_trend_long_keeps_break_even_once_activated() -> None:
    active_trade = _make_trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=100.0,
        take_profit=110.0,
        break_even_activated=True,
    )

    updated_trade = update_active_trade(
        active_trade=active_trade,
        latest_bb_middle=103.0,
        latest_close=106.0,
    )

    assert updated_trade is not None
    assert updated_trade.stop_loss == 100.0
    assert updated_trade.break_even_activated is True


def test_trend_short_updates_stop_loss_to_latest_bb_middle_before_break_even() -> None:
    active_trade = _make_trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.SHORT,
        entry=100.0,
        stop_loss=105.0,
        take_profit=90.0,
    )

    updated_trade = update_active_trade(
        active_trade=active_trade,
        latest_bb_middle=103.0,
        latest_close=97.0,
    )

    assert updated_trade is not None
    assert updated_trade.stop_loss == 103.0
    assert updated_trade.break_even_activated is False


def test_trend_short_stop_loss_only_tightens_and_never_widens() -> None:
    active_trade = _make_trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.SHORT,
        entry=100.0,
        stop_loss=102.0,
        take_profit=90.0,
    )

    updated_trade = update_active_trade(
        active_trade=active_trade,
        latest_bb_middle=104.0,
        latest_close=99.0,
    )

    assert updated_trade is not None
    assert updated_trade.stop_loss == 102.0


def test_trend_short_activates_break_even_at_1r() -> None:
    active_trade = _make_trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.SHORT,
        entry=100.0,
        stop_loss=105.0,
        take_profit=90.0,
    )

    updated_trade = update_active_trade(
        active_trade=active_trade,
        latest_bb_middle=103.0,
        latest_close=95.0,
    )

    assert updated_trade is not None
    assert updated_trade.stop_loss == 100.0
    assert updated_trade.break_even_activated is True


def test_trend_short_keeps_break_even_once_activated() -> None:
    active_trade = _make_trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.SHORT,
        entry=100.0,
        stop_loss=100.0,
        take_profit=90.0,
        break_even_activated=True,
    )

    updated_trade = update_active_trade(
        active_trade=active_trade,
        latest_bb_middle=97.0,
        latest_close=94.0,
    )

    assert updated_trade is not None
    assert updated_trade.stop_loss == 100.0
    assert updated_trade.break_even_activated is True


def test_trend_trade_unchanged_if_initial_risk_is_invalid_for_long() -> None:
    active_trade = _make_trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=100.0,
        take_profit=110.0,
    )

    updated_trade = update_active_trade(
        active_trade=active_trade,
        latest_bb_middle=97.0,
        latest_close=104.0,
    )

    assert updated_trade is not None
    assert updated_trade == active_trade


def test_trend_trade_unchanged_if_initial_risk_is_invalid_for_short() -> None:
    active_trade = _make_trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.SHORT,
        entry=100.0,
        stop_loss=100.0,
        take_profit=90.0,
    )

    updated_trade = update_active_trade(
        active_trade=active_trade,
        latest_bb_middle=103.0,
        latest_close=96.0,
    )

    assert updated_trade is not None
    assert updated_trade == active_trade


def test_countertrend_updates_only_take_profit() -> None:
    active_trade = _make_trade(
        trade_type=TradeType.COUNTERTREND,
        direction=TradeDirection.SHORT,
        entry=100.0,
        stop_loss=110.0,
        take_profit=95.0,
        break_even_activated=False,
    )

    updated_trade = update_active_trade(
        active_trade=active_trade,
        latest_bb_middle=98.0,
        latest_close=99.0,
    )

    assert updated_trade is not None
    assert updated_trade.take_profit == 98.0
    assert updated_trade.stop_loss == 110.0
    assert updated_trade.break_even_activated is False


def test_countertrend_long_updates_tp_only() -> None:
    active_trade = _make_trade(
        trade_type=TradeType.COUNTERTREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=90.0,
        take_profit=105.0,
    )

    updated_trade = update_active_trade(
        active_trade=active_trade,
        latest_bb_middle=99.0,
        latest_close=101.0,
    )

    assert updated_trade is not None
    assert updated_trade.take_profit == 99.0
    assert updated_trade.stop_loss == 90.0


def test_countertrend_long_updates_tp_with_buy_spread() -> None:
    active_trade = _make_trade(
        trade_type=TradeType.COUNTERTREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=90.0,
        take_profit=105.0,
    )

    updated_trade = update_active_trade(
        active_trade=active_trade,
        latest_bb_middle=99.0,
        latest_close=101.0,
        buy_spread=1.5,
    )

    assert updated_trade is not None
    assert updated_trade.take_profit == 100.5
    assert updated_trade.stop_loss == 90.0


def test_countertrend_short_updates_tp_only() -> None:
    active_trade = _make_trade(
        trade_type=TradeType.COUNTERTREND,
        direction=TradeDirection.SHORT,
        entry=100.0,
        stop_loss=110.0,
        take_profit=95.0,
    )

    updated_trade = update_active_trade(
        active_trade=active_trade,
        latest_bb_middle=97.0,
        latest_close=98.0,
    )

    assert updated_trade is not None
    assert updated_trade.take_profit == 97.0
    assert updated_trade.stop_loss == 110.0
