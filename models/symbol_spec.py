from decimal import Decimal

from pydantic import BaseModel, Field


class SymbolSpec(BaseModel):
    symbol: str
    asset: str
    base: str
    quote: str
    quantity_decimals: int = Field(ge=0)
    price_decimals: int | None = Field(default=None, ge=0)
    max_leverage: int | None = Field(default=None, ge=1)
    contract_multiplier: Decimal = Decimal("1")
    source_name: str = "unknown"
