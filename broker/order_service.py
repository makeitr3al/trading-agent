from __future__ import annotations

from decimal import Decimal
from typing import Any

from broker.propr_client import ProprClient
from models.order import Order, OrderType

# TODO: The SDK create_order call currently has no direct stop-loss / take-profit fields.
# TODO: Later map stop loss / take profit to proper child-order or bracket-order support if the SDK adds it.


def _require_non_empty(value: str, field_name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _parse_symbol(symbol: str) -> tuple[str, str, str]:
    normalized = _require_non_empty(symbol, "symbol")
    parts = normalized.split("/")
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise ValueError("symbol must be in BASE/QUOTE format")

    base = parts[0].strip()
    quote = parts[1].strip()
    asset = f"{base}/{quote}"
    return asset, base, quote


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


def generate_intent_id() -> str:
    from ulid import ULID

    return str(ULID())


def build_order_submission_preview(
    order: Order,
    symbol: str,
    reduce_only: bool = False,
    close_position: bool = False,
) -> dict[str, Any]:
    asset, base, quote = _parse_symbol(symbol)

    if order.position_size is None:
        raise ValueError("position_size is required")

    position_size = _to_decimal(order.position_size)
    if position_size <= Decimal("0"):
        raise ValueError("position_size must be positive")

    params: dict[str, Any] = {
        "asset": asset,
        "base": base,
        "quote": quote,
        "quantity": _serialize_decimal(position_size),
        "time_in_force": "GTC",
        "reduce_only": reduce_only,
        "close_position": close_position,
        "intent_id": generate_intent_id(),
    }

    if order.order_type == OrderType.BUY_LIMIT:
        params.update(
            {
                "side": "buy",
                "position_side": "long",
                "order_type": "limit",
                "price": _serialize_decimal(order.entry),
                "trigger_price": None,
            }
        )
    elif order.order_type == OrderType.SELL_LIMIT:
        params.update(
            {
                "side": "sell",
                "position_side": "short",
                "order_type": "limit",
                "price": _serialize_decimal(order.entry),
                "trigger_price": None,
            }
        )
    elif order.order_type == OrderType.BUY_STOP:
        entry = _serialize_decimal(order.entry)
        params.update(
            {
                "side": "buy",
                "position_side": "long",
                "order_type": "stop_limit",
                "price": entry,
                "trigger_price": entry,
            }
        )
    elif order.order_type == OrderType.SELL_STOP:
        entry = _serialize_decimal(order.entry)
        params.update(
            {
                "side": "sell",
                "position_side": "short",
                "order_type": "stop_limit",
                "price": entry,
                "trigger_price": entry,
            }
        )
    else:
        raise ValueError("unsupported order type")

    return params


def build_sdk_create_order_params(submission_preview: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in submission_preview.items()
        if key != "intent_id"
    }


def map_internal_order_to_propr_payload(
    order: Order,
    symbol: str,
    reduce_only: bool = False,
    close_position: bool = False,
) -> dict[str, Any]:
    return build_order_submission_preview(
        order,
        symbol,
        reduce_only=reduce_only,
        close_position=close_position,
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

    def submit_pending_order(
        self,
        account_id: str,
        order: Order,
        symbol: str,
        reduce_only: bool = False,
        close_position: bool = False,
        submission_preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_account_id = _require_non_empty(account_id, "account_id")
        preview = submission_preview or build_order_submission_preview(
            order,
            symbol,
            reduce_only=reduce_only,
            close_position=close_position,
        )
        order_params = build_sdk_create_order_params(preview)
        response = self.client.create_order(normalized_account_id, **order_params)
        ensured = _ensure_success_response(response, "create")
        if ensured is None:
            raise ValueError("Create order returned no response")
        return ensured

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
    "build_order_submission_preview",
    "build_sdk_create_order_params",
    "map_internal_order_to_propr_payload",
    "extract_order_id_from_submit_response",
    "ProprOrderService",
]
