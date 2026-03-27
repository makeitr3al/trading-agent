from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from pydantic import BaseModel

from broker.symbol_service import round_quantity_to_symbol_spec
from models.symbol_spec import SymbolSpec


class PositionSizeResult(BaseModel):
    position_size: float | None
    applied_leverage: int
    was_margin_capped: bool = False
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
            reason="entry must be positive",
        )

    risk_per_unit = abs(entry_decimal - stop_loss_decimal)
    if risk_per_unit <= Decimal("0"):
        return PositionSizeResult(
            position_size=None,
            applied_leverage=leverage,
            reason="risk per unit must be positive",
        )

    risk_amount = balance_decimal * risk_pct_decimal
    risk_based_size = risk_amount / risk_per_unit

    # Hyperliquid perps use size in units of the base asset. Margin scales with
    # notional / leverage, so we cap size by balance * leverage / entry.
    leverage_based_max_size = (balance_decimal * Decimal(leverage)) / entry_decimal
    was_margin_capped = leverage_based_max_size < risk_based_size
    sized = min(risk_based_size, leverage_based_max_size)

    if symbol_spec is not None:
        sized = round_quantity_to_symbol_spec(sized, symbol_spec)
    else:
        sized = sized.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

    if sized <= Decimal("0"):
        return PositionSizeResult(
            position_size=None,
            applied_leverage=leverage,
            was_margin_capped=was_margin_capped,
            reason="position size rounds to zero",
        )

    return PositionSizeResult(
        position_size=float(sized),
        applied_leverage=leverage,
        was_margin_capped=was_margin_capped,
        reason=None,
    )
