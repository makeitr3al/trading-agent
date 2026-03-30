from pydantic import BaseModel

from models.order import Order
from models.trade import Trade


class AgentState(BaseModel):
    active_trade: Trade | None = None
    pending_order: Order | None = None
    pending_order_id: str | None = None
    stop_loss_order_id: str | None = None
    take_profit_order_id: str | None = None
    last_decision_action: str | None = None
    last_signal_type: str | None = None
    last_regime: str | None = None
    middle_band_retest_required: bool = False
    trend_signal_consumed_in_regime: bool = False
    countertrend_long_signal_consumed_in_regime: bool = False
    countertrend_short_signal_consumed_in_regime: bool = False
    last_cycle_timestamp: str | None = None
    account_open_entry_orders_count: int = 0
    account_open_positions_count: int = 0
    account_unrealized_pnl: float | None = None
