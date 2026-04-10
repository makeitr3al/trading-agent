from pydantic import BaseModel


class ProprChallengeAttempt(BaseModel):
    attempt_id: str
    account_id: str
    challenge_id: str | None = None
    status: str
    current_phase: str | None = None
    total_profit_loss: float | None = None
    win_rate: float | None = None
    max_drawdown: float | None = None
    trading_days: int | None = None
    failure_reason: str | None = None


class AccountBalance(BaseModel):
    balance: float
    total_unrealized_pnl: float
    margin_balance: float
    available_balance: float
    high_water_mark: float
    initial_balance: float


class ActiveChallengeContext(BaseModel):
    attempt: ProprChallengeAttempt
    account_id: str
    challenge_id: str | None = None
    challenge_name: str | None = None
    account_balance: AccountBalance | None = None
