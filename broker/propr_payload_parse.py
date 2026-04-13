from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from models.order import OrderStatus
from utils.propr_response import get_first_key


def _get_items(payload: dict | list[dict]) -> list[dict]:
    if isinstance(payload, list):
        return payload
    data = payload.get("data", [])
    if isinstance(data, list):
        return data
    return []


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _extract_decimal(payload: dict[str, Any], keys: list[str]) -> Decimal | None:
    return _to_decimal(get_first_key(payload, keys))


def _normalize_side(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"buy", "long"}:
        return "long"
    if normalized in {"sell", "short"}:
        return "short"
    return None


def _normalize_order_type(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower().replace("-", "_")
    if normalized in {"stop", "stop_order", "buy_stop", "sell_stop", "stop_limit", "stop_market"}:
        return "stop"
    if normalized in {"limit", "limit_order", "buy_limit", "sell_limit", "take_profit_limit"}:
        return "limit"
    return None


def _normalize_status(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower().replace("-", "_")
    return normalized or None


def _map_order_status(value: Any) -> OrderStatus | None:
    normalized = _normalize_status(value)
    if normalized is None:
        return None
    if normalized in {
        "pending",
        "open",
        "new",
        "partially_filled",
        "partial_fill",
        "working",
        "accepted",
        "active",
        "live",
        "triggered",
    }:
        return OrderStatus.PENDING
    if normalized in {"filled", "executed", "closed"}:
        return OrderStatus.FILLED
    if normalized in {"cancelled", "canceled", "rejected", "expired"}:
        return OrderStatus.CANCELLED
    return None


def _is_open_position_status(value: Any) -> bool:
    return _normalize_status(value) in {"open", "active", "live"}


def _raw_order_type(value: Any) -> str | None:
    normalized = _normalize_status(value)
    return normalized or None


def _truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes"}


def _normalize_symbol(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def _extract_payload_symbol(payload: dict[str, Any]) -> str | None:
    direct_symbol = _normalize_symbol(
        get_first_key(payload, ["symbol", "asset", "market", "instrument"])
    )
    if direct_symbol is not None:
        return direct_symbol

    base = _normalize_symbol(get_first_key(payload, ["base"]))
    quote = _normalize_symbol(get_first_key(payload, ["quote"]))
    if base and quote:
        return f"{base}/{quote}"

    return _normalize_symbol(get_first_key(payload, ["coin"]))


def _payload_matches_symbol(payload: dict[str, Any], symbol: str | None) -> bool:
    if symbol is None:
        return True
    payload_symbol = _extract_payload_symbol(payload)
    if payload_symbol is None:
        return True
    return payload_symbol == symbol.strip().upper()
