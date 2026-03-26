from pydantic import BaseModel


class ProprChallengeAttempt(BaseModel):
    attempt_id: str
    account_id: str
    status: str
    current_phase: str | None = None
    total_profit_loss: float | None = None
    win_rate: float | None = None
    max_drawdown: float | None = None
    trading_days: int | None = None
    failure_reason: str | None = None


class ActiveChallengeContext(BaseModel):
    attempt: ProprChallengeAttempt
    account_id: str
