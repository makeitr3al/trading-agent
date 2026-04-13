"""Shared helpers for reading Propr REST / SDK response dicts (no broker or app imports)."""

from __future__ import annotations

from typing import Any


def get_first_key(payload: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def extract_external_order_id(payload: dict[str, Any] | None) -> str | None:
    """Resolve an external order id from a response or order row (top-level or nested ``data``)."""
    if payload is None or not isinstance(payload, dict):
        return None

    direct_value = get_first_key(payload, ["id", "orderId", "order_id"])
    if direct_value is not None:
        text = str(direct_value).strip()
        return text or None

    nested_payload = payload.get("data")
    if isinstance(nested_payload, list) and nested_payload:
        first_item = nested_payload[0]
        if isinstance(first_item, dict):
            nested_value = get_first_key(first_item, ["id", "orderId", "order_id"])
            if nested_value is not None:
                text = str(nested_value).strip()
                return text or None

    if isinstance(nested_payload, dict):
        nested_value = get_first_key(nested_payload, ["id", "orderId", "order_id"])
        if nested_value is not None:
            text = str(nested_value).strip()
            return text or None

    return None
