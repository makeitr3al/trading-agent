from __future__ import annotations

import hashlib
import os
from decimal import Decimal
from typing import Any

from broker.propr_client import ProprClient
from broker.symbol_service import round_price_to_symbol_spec, round_quantity_to_symbol_spec
from models.order import Order, OrderType
from models.symbol_spec import SymbolSpec
from models.trade import Trade, TradeDirection

# TODO: The SDK create_order call currently has no direct stop-loss / take-profit child-order support.
# TODO: Later map stop loss / take profit to proper bracket-order handling if the SDK adds it.


def _require_non_empty(value: str, field_name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()



def _parse_symbol(symbol: str) -> tuple[str, str, str]:
    normalized = _require_non_empty(symbol, "symbol")
    from utils.asset_normalizer import normalize_asset
    info = normalize_asset(normalized)
    return info.asset, info.base, info.quote



def _to_decimal(value: float | int | str | Decimal) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))



def _serialize_decimal(value: float | int | str | Decimal) -> str:
    decimal_value = _to_decimal(value)
    return format(decimal_value, "f")



def _parse_numeric_status(response: dict[str, Any]) -> int | None:
    raw_status = response.get("status") or response.get("status_code")
    if raw_status is None:
        return None
    if isinstance(raw_status, int):
        return raw_status

    text = str(raw_status).strip()
    if text.isdigit():
        return int(text)
    return None



def _normalize_buy_spread(buy_spread: float) -> float:
    return max(0.0, float(buy_spread))



def _apply_buy_spread_to_price(side: str, price: float | int | str | Decimal, buy_spread: float) -> Decimal:
    decimal_price = _to_decimal(price)
    if side.strip().lower() != "buy":
        return decimal_price
    return decimal_price + _to_decimal(_normalize_buy_spread(buy_spread))



def _exit_order_side_and_position(active_trade: Trade) -> tuple[str, str]:
    if active_trade.direction == TradeDirection.LONG:
        return "sell", "long"
    return "buy", "short"



def generate_intent_id() -> str:
    from ulid import ULID

    return str(ULID())


def _stable_intent_id_env_enabled() -> bool:
    return os.environ.get("PROPR_STABLE_INTENT_ID", "").strip().upper() == "YES"


def derive_stable_intent_id(seed: str) -> str:
    """Deterministic 26-char id from seed (Crockford-ish charset) for optional submit idempotency."""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    out: list[str] = []
    n = int(digest[:32], 16)
    for _ in range(26):
        n, r = divmod(n, 32)
        out.append(alphabet[r])
    return "".join(out)



def apply_symbol_spec_to_order(order: Order, symbol_spec: SymbolSpec | None) -> Order:
    if symbol_spec is None:
        return order

    updates: dict[str, float | str] = {
        "entry": float(round_price_to_symbol_spec(order.entry, symbol_spec)),
        "stop_loss": float(round_price_to_symbol_spec(order.stop_loss, symbol_spec)),
        "take_profit": float(round_price_to_symbol_spec(order.take_profit, symbol_spec)),
    }
    if order.position_size is not None:
        updates["position_size"] = float(round_quantity_to_symbol_spec(order.position_size, symbol_spec))
    return order.model_copy(update=updates)



def build_manual_order_submission_preview(
    symbol: str,
    side: str,
    position_side: str,
    order_type: str,
    quantity: float | int | str | Decimal,
    price: float | int | str | Decimal | None = None,
    trigger_price: float | int | str | Decimal | None = None,
    reduce_only: bool = False,
    close_position: bool = False,
    time_in_force: str | None = None,
    internal_stop_loss: float | int | str | Decimal | None = None,
    internal_take_profit: float | int | str | Decimal | None = None,
    position_id: str | None = None,
    intent_id: str | None = None,
) -> dict[str, Any]:
    asset, base, quote = _parse_symbol(symbol)
    normalized_side = _require_non_empty(side, "side").lower()
    normalized_position_side = _require_non_empty(position_side, "position_side").lower()
    normalized_order_type = _require_non_empty(order_type, "order_type").lower()

    quantity_decimal = _to_decimal(quantity)
    if quantity_decimal <= Decimal("0"):
        raise ValueError("quantity must be positive")

    params: dict[str, Any] = {
        "asset": asset,
        "base": base,
        "quote": quote,
        "side": normalized_side,
        "position_side": normalized_position_side,
        "order_type": normalized_order_type,
        "quantity": _serialize_decimal(quantity_decimal),
        "time_in_force": time_in_force or ("IOC" if normalized_order_type == "market" else "GTC"),
        "reduce_only": reduce_only,
        "close_position": close_position,
        "intent_id": intent_id or generate_intent_id(),
        # The sandbox may require position_id for conditional exit orders.
        "position_id": position_id,
    }
    if price is not None:
        params["price"] = _serialize_decimal(price)
    else:
        params["price"] = None
    if trigger_price is not None:
        params["trigger_price"] = _serialize_decimal(trigger_price)
    else:
        params["trigger_price"] = None
    if internal_stop_loss is not None:
        params["internal_stop_loss"] = _serialize_decimal(internal_stop_loss)
    if internal_take_profit is not None:
        params["internal_take_profit"] = _serialize_decimal(internal_take_profit)

    return params



def build_order_submission_preview(
    order: Order,
    symbol: str,
    reduce_only: bool = False,
    close_position: bool = False,
    symbol_spec: SymbolSpec | None = None,
    stable_intent_seed: str | None = None,
) -> dict[str, Any]:
    prepared_order = apply_symbol_spec_to_order(order, symbol_spec)

    if prepared_order.position_size is None:
        raise ValueError("position_size is required")
    if _to_decimal(prepared_order.position_size) <= Decimal("0"):
        raise ValueError("position_size must be positive")

    resolved_intent: str | None = None
    if stable_intent_seed is not None and _stable_intent_id_env_enabled():
        resolved_intent = derive_stable_intent_id(stable_intent_seed)

    params = build_manual_order_submission_preview(
        symbol=symbol,
        side="buy" if prepared_order.order_type in {OrderType.BUY_LIMIT, OrderType.BUY_STOP} else "sell",
        position_side="long" if prepared_order.order_type in {OrderType.BUY_LIMIT, OrderType.BUY_STOP} else "short",
        order_type="limit",
        quantity=prepared_order.position_size,
        reduce_only=reduce_only,
        close_position=close_position,
        internal_stop_loss=prepared_order.stop_loss,
        internal_take_profit=prepared_order.take_profit,
        intent_id=resolved_intent,
    )

    if prepared_order.order_type == OrderType.BUY_LIMIT:
        params.update(
            {
                "order_type": "limit",
                "price": _serialize_decimal(prepared_order.entry),
                "trigger_price": None,
            }
        )
    elif prepared_order.order_type == OrderType.SELL_LIMIT:
        params.update(
            {
                "order_type": "limit",
                "price": _serialize_decimal(prepared_order.entry),
                "trigger_price": None,
            }
        )
    elif prepared_order.order_type == OrderType.BUY_STOP:
        entry = _serialize_decimal(prepared_order.entry)
        params.update(
            {
                "order_type": "stop_limit",
                "price": entry,
                "trigger_price": entry,
            }
        )
    elif prepared_order.order_type == OrderType.SELL_STOP:
        entry = _serialize_decimal(prepared_order.entry)
        params.update(
            {
                "order_type": "stop_limit",
                "price": entry,
                "trigger_price": entry,
            }
        )
    else:
        raise ValueError("unsupported order type")

    return params



def build_market_close_submission_preview(
    active_trade: Trade,
    symbol: str,
) -> dict[str, Any]:
    if active_trade.quantity is None:
        raise ValueError("active trade quantity is required for market close")
    if _to_decimal(active_trade.quantity) <= Decimal("0"):
        raise ValueError("active trade quantity must be positive for market close")

    side, position_side = _exit_order_side_and_position(active_trade)
    return build_manual_order_submission_preview(
        symbol=symbol,
        side=side,
        position_side=position_side,
        order_type="market",
        quantity=active_trade.quantity,
        reduce_only=True,
        close_position=True,
        position_id=active_trade.position_id,
    )



def build_stop_loss_submission_preview(
    active_trade: Trade,
    symbol: str,
    buy_spread: float = 0.0,
) -> dict[str, Any]:
    if active_trade.quantity is None:
        raise ValueError("active trade quantity is required for stop-loss exit")
    if active_trade.position_id is None:
        raise ValueError("active trade position_id is required for stop-loss exit")

    side, position_side = _exit_order_side_and_position(active_trade)
    trigger_price = _apply_buy_spread_to_price(side, active_trade.stop_loss, buy_spread)
    return build_manual_order_submission_preview(
        symbol=symbol,
        side=side,
        position_side=position_side,
        order_type="stop_market",
        quantity=active_trade.quantity,
        trigger_price=trigger_price,
        reduce_only=True,
        close_position=False,
        position_id=active_trade.position_id,
    )



def build_take_profit_submission_preview(
    active_trade: Trade,
    symbol: str,
    buy_spread: float = 0.0,
) -> dict[str, Any]:
    if active_trade.quantity is None:
        raise ValueError("active trade quantity is required for take-profit exit")
    if active_trade.position_id is None:
        raise ValueError("active trade position_id is required for take-profit exit")
    if active_trade.take_profit is None:
        raise ValueError("active trade take_profit is required for take-profit exit")

    side, position_side = _exit_order_side_and_position(active_trade)
    take_profit_price = _apply_buy_spread_to_price(side, active_trade.take_profit, buy_spread)
    return build_manual_order_submission_preview(
        symbol=symbol,
        side=side,
        position_side=position_side,
        order_type="take_profit_limit",
        quantity=active_trade.quantity,
        price=take_profit_price,
        trigger_price=take_profit_price,
        reduce_only=True,
        close_position=False,
        position_id=active_trade.position_id,
    )



def build_sdk_create_order_params(submission_preview: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in submission_preview.items()
        if key not in {"internal_stop_loss", "internal_take_profit"} and value is not None
    }



def map_internal_order_to_propr_payload(
    order: Order,
    symbol: str,
    reduce_only: bool = False,
    close_position: bool = False,
    symbol_spec: SymbolSpec | None = None,
    stable_intent_seed: str | None = None,
) -> dict[str, Any]:
    return build_order_submission_preview(
        order,
        symbol,
        reduce_only=reduce_only,
        close_position=close_position,
        symbol_spec=symbol_spec,
        stable_intent_seed=stable_intent_seed,
    )



def _ensure_success_response(response: dict[str, Any] | None, operation: str) -> dict[str, Any] | None:
    if response is None:
        return None

    status = _parse_numeric_status(response)
    if status is None:
        return response

    if status in {200, 201}:
        return response

    raise ValueError(f"Unexpected {operation} response status: {status}")





def extract_order_id_from_submit_response(response: dict[str, Any]) -> str | None:
    data = response.get("data")
    if isinstance(data, list) and data:
        first_item = data[0]
        if isinstance(first_item, dict):
            for key in ["orderId", "order_id", "id"]:
                value = first_item.get(key)
                if value is not None:
                    text = str(value).strip()
                    return text or None

    for key in ["orderId", "order_id", "id"]:
        value = response.get(key)
        if value is not None:
            text = str(value).strip()
            return text or None

    return None


class ProprOrderService:
    def __init__(self, client: ProprClient) -> None:
        self.client = client

    def submit_order_preview(
        self,
        account_id: str,
        submission_preview: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_account_id = _require_non_empty(account_id, "account_id")
        order_params = build_sdk_create_order_params(submission_preview)
        response = self.client.create_order(normalized_account_id, **order_params)
        ensured = _ensure_success_response(response, "create")
        if ensured is None:
            raise ValueError("Create order returned no response")
        return ensured

    def submit_pending_order(
        self,
        account_id: str,
        order: Order,
        symbol: str,
        reduce_only: bool = False,
        close_position: bool = False,
        submission_preview: dict[str, Any] | None = None,
        symbol_spec: SymbolSpec | None = None,
        stable_intent_seed: str | None = None,
    ) -> dict[str, Any]:
        normalized_account_id = _require_non_empty(account_id, "account_id")
        preview = submission_preview or build_order_submission_preview(
            order,
            symbol,
            reduce_only=reduce_only,
            close_position=close_position,
            symbol_spec=symbol_spec,
            stable_intent_seed=stable_intent_seed,
        )
        return self.submit_order_preview(normalized_account_id, preview)

    def submit_market_close(
        self,
        account_id: str,
        active_trade: Trade,
        symbol: str,
    ) -> dict[str, Any]:
        normalized_account_id = _require_non_empty(account_id, "account_id")
        preview = build_market_close_submission_preview(active_trade, symbol)
        return self.submit_order_preview(normalized_account_id, preview)

    def submit_stop_loss_exit(
        self,
        account_id: str,
        active_trade: Trade,
        symbol: str,
        buy_spread: float = 0.0,
    ) -> dict[str, Any]:
        normalized_account_id = _require_non_empty(account_id, "account_id")
        preview = build_stop_loss_submission_preview(active_trade, symbol, buy_spread=buy_spread)
        return self.submit_order_preview(normalized_account_id, preview)

    def submit_take_profit_exit(
        self,
        account_id: str,
        active_trade: Trade,
        symbol: str,
        buy_spread: float = 0.0,
    ) -> dict[str, Any]:
        normalized_account_id = _require_non_empty(account_id, "account_id")
        preview = build_take_profit_submission_preview(active_trade, symbol, buy_spread=buy_spread)
        return self.submit_order_preview(normalized_account_id, preview)

    def cancel_order(
        self,
        account_id: str,
        order_id: str,
    ) -> dict[str, Any] | None:
        normalized_account_id = _require_non_empty(account_id, "account_id")
        normalized_order_id = _require_non_empty(order_id, "order_id")
        response = self.client.cancel_order(normalized_account_id, normalized_order_id)
        return _ensure_success_response(response, "cancel")


__all__ = [
    "generate_intent_id",
    "derive_stable_intent_id",
    "apply_symbol_spec_to_order",
    "build_manual_order_submission_preview",
    "build_order_submission_preview",
    "build_market_close_submission_preview",
    "build_stop_loss_submission_preview",
    "build_take_profit_submission_preview",
    "build_sdk_create_order_params",
    "map_internal_order_to_propr_payload",
    "extract_order_id_from_submit_response",
    "ProprOrderService",
]

