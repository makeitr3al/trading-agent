from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from pydantic import BaseModel

from broker.symbol_service import round_quantity_to_symbol_spec
from models.symbol_spec import SymbolSpec


class PositionSizeResult(BaseModel):
    position_size: float | None
    applied_leverage: int
    raw_position_size: float | None = None
    risk_amount: float | None = None
    risk_per_unit: float | None = None
    reason: str | None = None


class PositionSizeExecutionResult(BaseModel):
    allow_execution: bool
    desired_leverage: int
    max_leverage: int | None = None
    required_notional: float | None = None
    required_leverage: float | None = None
    reason: str | None = None



def _to_decimal(value: float | int | str | Decimal) -> Decimal:
    return Decimal(str(value))



def calculate_position_size(
    entry: float,
    stop_loss: float,
    account_balance: float,
    risk_per_trade_pct: float,
    desired_leverage: int = 1,
    symbol_spec: SymbolSpec | None = None,
) -> PositionSizeResult:
    entry_decimal = _to_decimal(entry)
    stop_loss_decimal = _to_decimal(stop_loss)
    balance_decimal = _to_decimal(account_balance)
    risk_pct_decimal = _to_decimal(risk_per_trade_pct)
    leverage = max(int(desired_leverage), 1)

    if entry_decimal <= Decimal("0"):
        return PositionSizeResult(
            position_size=None,
            applied_leverage=leverage,
            raw_position_size=None,
            risk_amount=None,
            risk_per_unit=None,
            reason="entry must be positive",
        )

    risk_per_unit = abs(entry_decimal - stop_loss_decimal)
    if risk_per_unit <= Decimal("0"):
        return PositionSizeResult(
            position_size=None,
            applied_leverage=leverage,
            raw_position_size=None,
            risk_amount=None,
            risk_per_unit=None,
            reason="risk per unit must be positive",
        )

    risk_amount = balance_decimal * risk_pct_decimal
    risk_based_size = risk_amount / risk_per_unit
    sized = risk_based_size

    if symbol_spec is not None:
        sized = round_quantity_to_symbol_spec(sized, symbol_spec)
    else:
        sized = sized.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

    if sized <= Decimal("0"):
        return PositionSizeResult(
            position_size=None,
            applied_leverage=leverage,
            raw_position_size=float(risk_based_size),
            risk_amount=float(risk_amount),
            risk_per_unit=float(risk_per_unit),
            reason="position size rounds to zero",
        )

    return PositionSizeResult(
        position_size=float(sized),
        applied_leverage=leverage,
        raw_position_size=float(risk_based_size),
        risk_amount=float(risk_amount),
        risk_per_unit=float(risk_per_unit),
        reason=None,
    )


def evaluate_position_size_execution(
    entry: float,
    position_size: float,
    account_balance: float,
    desired_leverage: int = 1,
    max_leverage: int | None = None,
) -> PositionSizeExecutionResult:
    entry_decimal = _to_decimal(entry)
    position_size_decimal = _to_decimal(position_size)
    balance_decimal = _to_decimal(account_balance)
    leverage = max(int(desired_leverage), 1)

    if entry_decimal <= Decimal("0"):
        return PositionSizeExecutionResult(
            allow_execution=False,
            desired_leverage=leverage,
            max_leverage=max_leverage,
            reason="entry must be positive",
        )

    if position_size_decimal <= Decimal("0"):
        return PositionSizeExecutionResult(
            allow_execution=False,
            desired_leverage=leverage,
            max_leverage=max_leverage,
            reason="position size must be positive",
        )

    if balance_decimal <= Decimal("0"):
        return PositionSizeExecutionResult(
            allow_execution=False,
            desired_leverage=leverage,
            max_leverage=max_leverage,
            reason="account balance must be positive",
        )

    required_notional = entry_decimal * position_size_decimal
    required_leverage = required_notional / balance_decimal

    if required_leverage > Decimal(leverage):
        return PositionSizeExecutionResult(
            allow_execution=False,
            desired_leverage=leverage,
            max_leverage=max_leverage,
            required_notional=float(required_notional),
            required_leverage=float(required_leverage),
            reason="risk based position size exceeds desired leverage",
        )

    if max_leverage is not None and required_leverage > Decimal(max_leverage):
        return PositionSizeExecutionResult(
            allow_execution=False,
            desired_leverage=leverage,
            max_leverage=max_leverage,
            required_notional=float(required_notional),
            required_leverage=float(required_leverage),
            reason="risk based position size exceeds max allowed leverage",
        )

    return PositionSizeExecutionResult(
        allow_execution=True,
        desired_leverage=leverage,
        max_leverage=max_leverage,
        required_notional=float(required_notional),
        required_leverage=float(required_leverage),
        reason=None,
    )
