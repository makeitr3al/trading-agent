from pydantic import BaseModel, Field


class JournalSignalRecord(BaseModel):
    signal_type: str
    is_valid: bool
    reason: str


class JournalUnusedSignalRecord(BaseModel):
    signal_type: str
    reason: str


class JournalEntry(BaseModel):
    schema_version: int = 1
    entry_type: str
    entry_date: str
    entry_timestamp: str
    executed_at: str | None = None
    symbol: str
    environment: str | None = None
    decision_action: str | None = None
    skipped_reason: str | None = None
    received_signals: list[JournalSignalRecord] = Field(default_factory=list)
    used_signals: list[str] = Field(default_factory=list)
    unused_signals: list[JournalUnusedSignalRecord] = Field(default_factory=list)
    direction: str | None = None
    fill_timestamp: str | None = None
    close_timestamp: str | None = None
    position_size: float | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    close_price: float | None = None
    pnl: float | None = None
    status: str | None = None
    source_signal_type: str | None = None
    notes: str | None = None
    lifecycle_id: str | None = None
