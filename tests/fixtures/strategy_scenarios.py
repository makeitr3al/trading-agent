from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from config.strategy_config import StrategyConfig, build_strategy_config
from models.agent_state import AgentState
from models.candle import Candle
from models.trade import Trade, TradeDirection, TradeType


@dataclass
class StrategyGoldenScenario:
    name: str
    candles: list[Candle]
    config: StrategyConfig
    account_balance: float = 10000.0
    active_trade: Trade | None = None
    agent_state: AgentState | None = None
    expected_trend_signal_valid: bool | None = None
    expected_trend_signal_type: str | None = None
    expected_countertrend_signal_valid: bool | None = None
    expected_countertrend_signal_type: str | None = None
    expected_decision_action: str | None = None
    expected_order_present: bool | None = None
    expected_break_even_activated: bool | None = None
    expected_consumed_flag: bool | None = None
    expected_close_active_trade: bool | None = None
    expected_updated_stop_loss: float | None = None


BASE_TIME = datetime(2026, 1, 1, 0, 0, 0)
TREND_CONTEXT_CLOSES = [
    10.9,
    10.7,
    10.8,
    10.55,
    10.45,
    10.25,
    10.35,
    10.15,
    10.05,
    10.15,
    10.0,
    9.9,
    10.0,
    9.85,
    9.95,
    9.8,
]
BULLISH_REVERSAL_CONTEXT_CLOSES = [
    11.2,
    11.05,
    10.95,
    10.85,
    10.75,
    10.65,
    10.55,
    10.45,
    10.35,
    10.25,
    10.8,
    10.65,
    10.55,
    10.4,
    10.25,
    10.15,
    10.0,
    9.9,
    9.8,
    9.7,
    9.6,
    9.55,
    9.5,
    9.45,
    9.4,
    9.35,
]
BEARISH_REVERSAL_CONTEXT_CLOSES = [
    8.0,
    8.1,
    8.2,
    8.3,
    8.4,
    8.5,
    8.6,
    8.7,
    8.8,
    8.9,
    9.0,
    9.1,
    9.2,
    9.3,
    9.4,
    9.5,
    9.6,
    9.7,
    9.8,
    9.9,
    10.0,
    10.05,
    10.1,
    10.15,
    10.2,
    10.25,
]
LONGER_SWING_CLOSES = [
    100.0,
    100.5,
    101.0,
    100.8,
    101.4,
    102.0,
    101.7,
    102.5,
    103.1,
    102.9,
    103.4,
    104.0,
    103.8,
    104.6,
    105.1,
    104.9,
    105.5,
    106.0,
    105.7,
    106.4,
    107.0,
    106.8,
    107.3,
    108.0,
    107.6,
    108.4,
    109.0,
    108.7,
    109.5,
    110.0,
    109.8,
    110.4,
    111.0,
    110.6,
    111.3,
    112.0,
    111.8,
    112.4,
    113.0,
    112.7,
]


LIVE_TREND_LONG_CLOSES = [
    113277.0, 108962.0, 109614.0, 109599.0, 112130.0, 114274.0, 114036.0, 118572.0, 120516.0, 122266.0,
    122455.0, 123570.0, 124711.0, 121401.0, 123385.0, 121615.0, 112761.0, 110592.0, 114940.0, 115124.0,
    113020.0, 110730.0, 108221.0, 106396.0, 107143.0, 108591.0, 110479.0, 108245.0, 107528.0, 110063.0,
    111060.0, 111683.0, 114601.0, 114111.0, 112864.0, 110102.0, 108360.0, 109587.0, 110120.0, 110529.0,
    106527.0, 101460.0, 103925.0, 101313.0, 103300.0, 102269.0, 104753.0, 106015.0, 103034.0, 101623.0,
    99735.0, 94634.0, 95592.0, 94291.0, 92272.0, 92972.0, 91554.0, 86650.0, 85111.0, 84711.0,
    86807.0, 88232.0, 87332.0, 90420.0, 91310.0, 90842.0, 90768.0, 90326.0, 86216.0, 91237.0,
    93395.0, 92034.0, 89294.0, 89181.0, 90344.0, 90594.0, 92654.0, 91961.0, 92481.0, 90228.0,
    90222.0, 88128.0, 86427.0, 87814.0, 86210.0, 85477.0, 88092.0, 88317.0, 88607.0, 88573.0,
    87459.0, 87653.0, 87200.0, 87339.0, 87844.0, 87928.0, 87228.0, 88466.0, 87632.0, 88809.0,
    89932.0, 90600.0, 91511.0, 93832.0, 93801.0, 91373.0, 91079.0, 90650.0, 90485.0, 90997.0,
    91249.0, 95374.0, 96917.0, 95588.0, 95586.0, 95144.0, 93621.0, 92581.0, 88404.0, 89401.0,
    89500.0, 89552.0, 89171.0, 86637.0, 88299.0, 89215.0, 89276.0, 84641.0, 84241.0, 78728.0,
    76928.0, 78684.0, 75731.0, 73147.0, 62894.0, 70516.0, 69236.0, 70297.0, 70093.0, 68801.0,
    67059.0, 66244.0, 68822.0, 69792.0, 68798.0, 68870.0, 67480.0, 66436.0, 66981.0, 67980.0,
    67935.0, 67602.0, 64631.0, 64015.0, 67944.0, 67453.0, 65837.0, 66931.0, 65734.0, 68774.0,
    68299.0, 72633.0, 70828.0, 68082.0, 67230.0, 65933.0, 68389.0, 69898.0, 70135.0, 70500.0,
    70901.0, 71180.0, 72778.0, 74854.0, 73864.0, 71213.0, 69919.0, 70474.0, 68874.0, 67831.0,
    70860.0, 70553.0, 71303.0,
]

LIVE_SWEET_SPOT_CLOSES = [
    111670.0, 110741.0, 110646.0, 110139.0, 111102.0, 112035.0, 111563.0, 113954.0, 115489.0, 116023.0,
    115908.0, 115276.0, 115370.0, 116761.0, 116466.0, 117110.0, 115674.0, 115686.0, 115278.0, 112638.0,
    111976.0, 113277.0, 108962.0, 109614.0, 109599.0, 112130.0, 114274.0, 114036.0, 118572.0, 120516.0,
    122266.0, 122455.0, 123570.0, 124711.0, 121401.0, 123385.0, 121615.0, 112761.0, 110592.0, 114940.0,
    115124.0, 113020.0, 110730.0, 108221.0, 106396.0, 107143.0, 108591.0, 110479.0, 108245.0, 107528.0,
    110063.0, 111060.0, 111683.0, 114601.0, 114111.0, 112864.0, 110102.0, 108360.0, 109587.0, 110120.0,
    110529.0, 106527.0, 101460.0, 103925.0, 101313.0, 103300.0, 102269.0, 104753.0, 106015.0, 103034.0,
    101623.0, 99735.0, 94634.0, 95592.0, 94291.0, 92272.0, 92972.0, 91554.0, 86650.0, 85111.0,
    84711.0, 86807.0, 88232.0, 87332.0, 90420.0, 91310.0, 90842.0, 90768.0, 90326.0, 86216.0,
    91237.0, 93395.0, 92034.0, 89294.0, 89181.0, 90344.0, 90594.0, 92654.0, 91961.0, 92481.0,
    90228.0, 90222.0, 88128.0, 86427.0, 87814.0, 86210.0, 85477.0, 88092.0, 88317.0, 88607.0,
    88573.0, 87459.0, 87653.0, 87200.0, 87339.0, 87844.0, 87928.0, 87228.0, 88466.0, 87632.0,
    88809.0, 89932.0, 90600.0, 91511.0, 93832.0, 93801.0, 91373.0, 91079.0, 90650.0, 90485.0,
    90997.0, 91249.0, 95374.0, 96917.0, 95588.0, 95586.0, 95144.0, 93621.0, 92581.0, 88404.0,
    89401.0, 89500.0, 89552.0, 89171.0, 86637.0, 88299.0, 89215.0, 89276.0, 84641.0, 84241.0,
    78728.0, 76928.0, 78684.0, 75731.0, 73147.0, 62894.0, 70516.0, 69236.0, 70297.0, 70093.0,
    68801.0, 67059.0, 66244.0, 68822.0, 69792.0, 68798.0, 68870.0, 67480.0, 66436.0, 66981.0,
    67980.0, 67935.0, 67602.0, 64631.0, 64015.0, 67944.0, 67453.0, 65837.0, 66931.0, 65734.0,
    68774.0, 68299.0, 72633.0,
]

LIVE_TREND_REGIME_TOO_OLD_CLOSES = LIVE_TREND_LONG_CLOSES[:175]


ALLOWED_GOLDEN_CONFIG_OVERRIDES = {
    "max_bars_since_regime_start_for_trend_signal",
    "outside_band_sweet_spot",
}


def make_config(**overrides: float | int) -> StrategyConfig:
    disallowed_keys = set(overrides) - ALLOWED_GOLDEN_CONFIG_OVERRIDES
    if disallowed_keys:
        raise ValueError(
            "Golden scenarios must use the canonical live strategy config. "
            f"Unsupported overrides: {sorted(disallowed_keys)}"
        )
    return build_strategy_config(**overrides)


def _build_candles(
    closes: list[float],
    final_open: float | None = None,
    default_open_offset: float = -0.1,
    high_padding: float = 0.2,
    low_padding: float = 0.2,
) -> list[Candle]:
    candles: list[Candle] = []
    for index, close in enumerate(closes):
        open_price = close + default_open_offset
        if index == len(closes) - 1 and final_open is not None:
            open_price = final_open

        candles.append(
            Candle(
                timestamp=BASE_TIME + timedelta(days=index),
                open=float(open_price),
                high=float(max(open_price, close) + high_padding),
                low=float(min(open_price, close) - low_padding),
                close=float(close),
            )
        )
    return candles


def _prepend_context(tail: list[float], context: list[float]) -> list[float]:
    return context + tail


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


def _chart_scenario(
    name: str,
    closes: list[float],
    config: StrategyConfig,
    final_open: float | None = None,
    default_open_offset: float = -0.1,
    **expected: bool | str | float | None,
) -> StrategyGoldenScenario:
    return StrategyGoldenScenario(
        name=name,
        candles=_build_candles(
            closes,
            final_open=final_open,
            default_open_offset=default_open_offset,
        ),
        config=config,
        **expected,
    )


def _state_scenario(
    name: str,
    closes: list[float],
    config: StrategyConfig,
    active_trade: Trade | None = None,
    agent_state: AgentState | None = None,
    final_open: float | None = None,
    default_open_offset: float = -0.1,
    **expected: bool | str | float | None,
) -> StrategyGoldenScenario:
    return StrategyGoldenScenario(
        name=name,
        candles=_build_candles(
            closes,
            final_open=final_open,
            default_open_offset=default_open_offset,
        ),
        config=config,
        active_trade=active_trade,
        agent_state=agent_state,
        **expected,
    )


def valid_trend_long_scenario() -> StrategyGoldenScenario:
    return _chart_scenario(
        name="valid trend long",
        closes=LIVE_TREND_LONG_CLOSES,
        config=make_config(),
        expected_trend_signal_valid=True,
        expected_trend_signal_type="TREND_LONG",
        expected_countertrend_signal_valid=False,
        expected_decision_action="PREPARE_TREND_ORDER",
        expected_order_present=True,
    )


def invalid_trend_regime_too_old_scenario() -> StrategyGoldenScenario:
    return _chart_scenario(
        name="invalid trend regime too old",
        closes=LIVE_TREND_REGIME_TOO_OLD_CLOSES,
        config=make_config(max_bars_since_regime_start_for_trend_signal=2),
        expected_trend_signal_valid=False,
        expected_trend_signal_type="TREND_LONG",
        expected_countertrend_signal_valid=False,
        expected_decision_action="NO_ACTION",
        expected_order_present=False,
    )


def invalid_trend_candle_not_in_direction_scenario() -> StrategyGoldenScenario:
    return _chart_scenario(
        name="invalid trend candle not in direction",
        closes=LIVE_TREND_LONG_CLOSES,
        config=make_config(),
        final_open=72000.0,
        expected_trend_signal_valid=False,
        expected_trend_signal_type="TREND_LONG",
        expected_countertrend_signal_valid=False,
        expected_decision_action="NO_ACTION",
        expected_order_present=False,
    )


def valid_countertrend_short_first_bullish_regime_scenario() -> StrategyGoldenScenario:
    return _chart_scenario(
        name="valid countertrend short first bullish regime bar",
        closes=_prepend_context([9.6, 9.55, 9.5, 9.45, 9.4, 9.35, 11.0], BULLISH_REVERSAL_CONTEXT_CLOSES),
        config=make_config(),
        expected_trend_signal_valid=False,
        expected_countertrend_signal_valid=True,
        expected_countertrend_signal_type="COUNTERTREND_SHORT",
        expected_decision_action="PREPARE_COUNTERTREND_ORDER",
        expected_order_present=True,
    )


def sweet_spot_should_manage_active_trend_without_countertrend_signal_scenario() -> StrategyGoldenScenario:
    return _state_scenario(
        name="sweet spot manages active trend without countertrend signal",
        closes=LIVE_SWEET_SPOT_CLOSES,
        config=make_config(outside_band_sweet_spot=0.2),
        active_trade=_make_trade(
            TradeType.TREND,
            TradeDirection.LONG,
            entry=9.2,
            stop_loss=9.0,
            take_profit=9.9,
        ),
        expected_countertrend_signal_valid=False,
        expected_countertrend_signal_type="COUNTERTREND_SHORT",
        expected_decision_action="ADJUST_TREND_STOP_TO_LAST_CLOSE",
        expected_order_present=False,
        expected_close_active_trade=False,
        expected_updated_stop_loss=72633.0,
    )


def valid_countertrend_long_first_bearish_regime_scenario() -> StrategyGoldenScenario:
    return _chart_scenario(
        name="valid countertrend long first bearish regime bar",
        closes=_prepend_context([10.4, 10.45, 10.5, 10.55, 10.6, 10.65, 9.0], BEARISH_REVERSAL_CONTEXT_CLOSES),
        config=make_config(),
        final_open=9.1,
        expected_trend_signal_valid=False,
        expected_countertrend_signal_valid=True,
        expected_countertrend_signal_type="COUNTERTREND_LONG",
        expected_decision_action="PREPARE_COUNTERTREND_ORDER",
        expected_order_present=True,
    )


def no_countertrend_not_first_regime_bar_scenario() -> StrategyGoldenScenario:
    return _chart_scenario(
        name="no countertrend not first regime bar",
        closes=_prepend_context([9.6, 9.55, 9.5, 9.45, 9.4, 11.0, 11.3, 11.5, 11.6], BULLISH_REVERSAL_CONTEXT_CLOSES),
        config=make_config(),
        expected_trend_signal_valid=False,
        expected_countertrend_signal_valid=False,
        expected_countertrend_signal_type="COUNTERTREND_SHORT",
        expected_decision_action="NO_ACTION",
        expected_order_present=False,
    )


def trend_order_should_be_prepared_scenario() -> StrategyGoldenScenario:
    return _state_scenario(
        name="trend order should be prepared",
        closes=LIVE_TREND_LONG_CLOSES,
        config=make_config(),
        agent_state=AgentState(),
        expected_trend_signal_valid=True,
        expected_trend_signal_type="TREND_LONG",
        expected_decision_action="PREPARE_TREND_ORDER",
        expected_order_present=True,
        expected_consumed_flag=True,
    )


def countertrend_should_override_active_trend_trade_scenario() -> StrategyGoldenScenario:
    return _state_scenario(
        name="countertrend overrides active trend trade by locking stop",
        closes=_prepend_context([9.6, 9.55, 9.5, 9.45, 9.4, 9.35, 11.0], BULLISH_REVERSAL_CONTEXT_CLOSES),
        config=make_config(),
        active_trade=_make_trade(
            TradeType.TREND,
            TradeDirection.LONG,
            entry=10.2,
            stop_loss=9.7,
            take_profit=11.2,
        ),
        expected_countertrend_signal_valid=True,
        expected_countertrend_signal_type="COUNTERTREND_SHORT",
        expected_decision_action="ADJUST_TREND_STOP_TO_LAST_CLOSE",
        expected_order_present=False,
        expected_close_active_trade=False,
        expected_updated_stop_loss=11.0,
    )


def countertrend_should_close_active_trend_trade_scenario() -> StrategyGoldenScenario:
    return _state_scenario(
        name="countertrend closes active trend trade",
        closes=_prepend_context([10.4, 10.45, 10.5, 10.55, 10.6, 10.65, 9.0], BEARISH_REVERSAL_CONTEXT_CLOSES),
        config=make_config(),
        final_open=9.1,
        active_trade=_make_trade(
            TradeType.TREND,
            TradeDirection.SHORT,
            entry=8.8,
            stop_loss=9.4,
            take_profit=8.0,
        ),
        expected_countertrend_signal_valid=True,
        expected_countertrend_signal_type="COUNTERTREND_LONG",
        expected_decision_action="CLOSE_TREND_TRADE",
        expected_order_present=False,
        expected_close_active_trade=True,
    )


def break_even_should_activate_scenario() -> StrategyGoldenScenario:
    return _state_scenario(
        name="break even should activate",
        closes=LONGER_SWING_CLOSES,
        config=make_config(),
        active_trade=_make_trade(
            TradeType.TREND,
            TradeDirection.LONG,
            entry=100.0,
            stop_loss=95.0,
            take_profit=110.0,
        ),
        expected_break_even_activated=True,
    )


def countertrend_tp_should_update_scenario() -> StrategyGoldenScenario:
    return _state_scenario(
        name="countertrend tp should update",
        closes=LONGER_SWING_CLOSES,
        config=make_config(),
        active_trade=_make_trade(
            TradeType.COUNTERTREND,
            TradeDirection.SHORT,
            entry=100.0,
            stop_loss=110.0,
            take_profit=95.0,
        ),
        expected_break_even_activated=False,
    )


def trend_signal_consumed_duplicate_order_scenario() -> StrategyGoldenScenario:
    return _state_scenario(
        name="trend signal consumed duplicate order",
        closes=LIVE_TREND_LONG_CLOSES,
        config=make_config(),
        agent_state=AgentState(
            trend_signal_consumed_in_regime=True,
            last_regime="bullish",
        ),
        expected_trend_signal_valid=False,
        expected_trend_signal_type="TREND_LONG",
        expected_decision_action="NO_ACTION",
        expected_order_present=False,
        expected_consumed_flag=True,
    )


def regime_change_should_reset_consumed_flag_scenario() -> StrategyGoldenScenario:
    return _state_scenario(
        name="regime change should reset consumed flag",
        closes=LIVE_TREND_REGIME_TOO_OLD_CLOSES,
        config=make_config(max_bars_since_regime_start_for_trend_signal=2),
        agent_state=AgentState(
            trend_signal_consumed_in_regime=True,
            last_regime="bearish",
        ),
        expected_trend_signal_valid=False,
        expected_decision_action="NO_ACTION",
        expected_order_present=False,
        expected_consumed_flag=False,
    )


__all__ = [
    "StrategyGoldenScenario",
    "valid_trend_long_scenario",
    "invalid_trend_regime_too_old_scenario",
    "invalid_trend_candle_not_in_direction_scenario",
    "valid_countertrend_short_first_bullish_regime_scenario",
    "sweet_spot_should_manage_active_trend_without_countertrend_signal_scenario",
    "valid_countertrend_long_first_bearish_regime_scenario",
    "no_countertrend_not_first_regime_bar_scenario",
    "trend_order_should_be_prepared_scenario",
    "countertrend_should_override_active_trend_trade_scenario",
    "countertrend_should_close_active_trend_trade_scenario",
    "break_even_should_activate_scenario",
    "countertrend_tp_should_update_scenario",
    "trend_signal_consumed_duplicate_order_scenario",
    "regime_change_should_reset_consumed_flag_scenario",
]



