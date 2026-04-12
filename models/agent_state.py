from pydantic import BaseModel, Field, model_validator

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
    consumed_signals: set[str] = Field(default_factory=set)
    last_cycle_timestamp: str | None = None
    account_open_entry_orders_count: int = 0
    account_open_positions_count: int = 0
    account_unrealized_pnl: float | None = None
    signal_lifecycle_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _migrate_consumed_booleans(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        signals: set[str] = set(data.get("consumed_signals") or set())
        if data.pop("trend_signal_consumed_in_regime", False):
            signals.add("trend")
        if data.pop("countertrend_long_signal_consumed_in_regime", False):
            signals.add("countertrend_long")
        if data.pop("countertrend_short_signal_consumed_in_regime", False):
            signals.add("countertrend_short")
        data["consumed_signals"] = signals
        return data

    # Deprecated aliases — read via consumed_signals set
    @property
    def trend_signal_consumed_in_regime(self) -> bool:
        return "trend" in self.consumed_signals

    @property
    def countertrend_long_signal_consumed_in_regime(self) -> bool:
        return "countertrend_long" in self.consumed_signals

    @property
    def countertrend_short_signal_consumed_in_regime(self) -> bool:
        return "countertrend_short" in self.consumed_signals
