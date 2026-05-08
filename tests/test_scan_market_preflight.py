from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from utils.scan_market_preflight import (
    PreflightResult,
    _candidate_entries,
    preflight_scan_markets,
)


class _FakeResponse:
    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        return self._body


def _make_post(
    *,
    valid_coins: dict[str, dict[str, Any]] | None = None,
    structural_failures: dict[str, dict[str, Any]] | None = None,
):
    """Build a fake post() that simulates HL /info responses.

    valid_coins maps coin -> {"l2Book": dict, "candles": list}
    structural_failures maps coin -> {"l2Book": <dict-with-empty-levels>, "candle_status": 500}
    """
    valid_coins = valid_coins or {}
    structural_failures = structural_failures or {}
    call_log: list[tuple[str, str]] = []

    def post(payload: dict) -> _FakeResponse:
        ptype = payload.get("type")
        coin = payload.get("coin") or (payload.get("req") or {}).get("coin")
        call_log.append((ptype, coin))
        if coin in valid_coins:
            spec = valid_coins[coin]
            if ptype == "l2Book":
                return _FakeResponse(200, spec["l2Book"])
            if ptype == "candleSnapshot":
                return _FakeResponse(200, spec["candles"])
        if coin in structural_failures:
            spec = structural_failures[coin]
            if ptype == "l2Book":
                return _FakeResponse(spec.get("l2_status", 200), spec.get("l2Book", {"levels": [[], []]}))
            if ptype == "candleSnapshot":
                return _FakeResponse(spec.get("candle_status", 500), spec.get("candles", []))
        return _FakeResponse(404, {})

    post.call_log = call_log  # type: ignore[attr-defined]
    return post


def _good_l2() -> dict[str, Any]:
    return {"levels": [[{"px": "100.0", "sz": "1"}], [{"px": "100.5", "sz": "1"}]]}


def _good_candles() -> list[dict[str, Any]]:
    return [{"t": 1_700_000_000_000, "o": "1", "h": "2", "l": "0.5", "c": "1.5"}]


def test_candidate_entries_for_bare_ticker_adds_xyz_and_base() -> None:
    assert _candidate_entries("EUR") == ["EUR", "xyz:EUR"]


def test_candidate_entries_for_xyz_does_not_add_xyz_again() -> None:
    assert _candidate_entries("xyz:MSTR") == ["xyz:MSTR", "MSTR"]


def test_candidate_entries_for_other_prefix_tries_xyz_and_bare() -> None:
    # KM:GOOGL → tries KM:GOOGL (raw), then xyz:GOOGL, then GOOGL.
    assert _candidate_entries("KM:GOOGL") == ["KM:GOOGL", "xyz:GOOGL", "GOOGL"]


def test_preflight_passes_through_already_working_entry(tmp_path: Path) -> None:
    post = _make_post(valid_coins={"BTC": {"l2Book": _good_l2(), "candles": _good_candles()}})
    cache_path = tmp_path / "preflight.json"

    working, results = preflight_scan_markets(["BTC"], cache_path=cache_path, http_post=post)

    assert working == ["BTC"]
    assert len(results) == 1
    assert results[0].working_entry == "BTC"
    assert cache_path.exists()


def test_preflight_repairs_wrong_prefix_to_xyz(tmp_path: Path) -> None:
    # KM:GOOGL is structurally broken on /info; xyz:GOOGL works.
    post = _make_post(
        valid_coins={"xyz:GOOGL": {"l2Book": _good_l2(), "candles": _good_candles()}},
        structural_failures={"KM:GOOGL": {"l2Book": {"levels": [[], []]}, "candle_status": 500}},
    )
    cache_path = tmp_path / "preflight.json"

    working, results = preflight_scan_markets(["KM:GOOGL"], cache_path=cache_path, http_post=post)

    assert working == ["xyz:GOOGL"]
    assert results[0].raw == "KM:GOOGL"
    assert results[0].working_entry == "xyz:GOOGL"


def test_preflight_excludes_when_no_variant_works(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # KLUNC has no working form anywhere.
    post = _make_post(
        structural_failures={
            "KLUNC": {"l2Book": {"levels": [[], []]}, "candle_status": 500},
            "xyz:KLUNC": {"l2Book": {"levels": [[], []]}, "candle_status": 500},
        }
    )
    cache_path = tmp_path / "preflight.json"

    working, results = preflight_scan_markets(["KLUNC"], cache_path=cache_path, http_post=post)

    assert working == []
    assert results[0].working_entry is None
    assert results[0].reason is not None and "KLUNC" in results[0].reason
    err = capsys.readouterr().err
    assert "[preflight] excluded raw='KLUNC'" in err
    assert "1 market(s) excluded from scan: KLUNC" in err


def test_preflight_uses_cache_within_ttl(tmp_path: Path) -> None:
    cache_path = tmp_path / "preflight.json"
    cache_path.write_text(
        json.dumps(
            {
                "BTC": {
                    "raw": "BTC",
                    "working_entry": "BTC",
                    "reason": None,
                    "checked_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
                }
            }
        ),
        encoding="utf-8",
    )

    def _no_calls_post(_payload: dict) -> _FakeResponse:
        raise AssertionError("HTTP must not be called when cache is fresh")

    working, _ = preflight_scan_markets(
        ["BTC"], cache_path=cache_path, http_post=_no_calls_post, ttl_hours=24
    )
    assert working == ["BTC"]


def test_preflight_re_probes_after_ttl_expiry(tmp_path: Path) -> None:
    cache_path = tmp_path / "preflight.json"
    cache_path.write_text(
        json.dumps(
            {
                "BTC": {
                    "raw": "BTC",
                    "working_entry": None,
                    "reason": "BTC: candleSnapshot HTTP 500",
                    "checked_at": (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat(),
                }
            }
        ),
        encoding="utf-8",
    )
    post = _make_post(valid_coins={"BTC": {"l2Book": _good_l2(), "candles": _good_candles()}})

    working, _ = preflight_scan_markets(
        ["BTC"], cache_path=cache_path, http_post=post, ttl_hours=24
    )
    assert working == ["BTC"]
    assert any(call[0] == "candleSnapshot" for call in post.call_log)


def test_preflight_preserves_input_order_and_drops_excluded(tmp_path: Path) -> None:
    post = _make_post(
        valid_coins={
            "BTC": {"l2Book": _good_l2(), "candles": _good_candles()},
            "xyz:GOOGL": {"l2Book": _good_l2(), "candles": _good_candles()},
            "ETH": {"l2Book": _good_l2(), "candles": _good_candles()},
        },
        structural_failures={
            "KM:GOOGL": {"l2Book": {"levels": [[], []]}, "candle_status": 500},
            "FLX:OIL": {"l2Book": {"levels": [[], []]}, "candle_status": 500},
            "xyz:OIL": {"l2Book": {"levels": [[], []]}, "candle_status": 500},
            "OIL": {"l2Book": {"levels": [[], []]}, "candle_status": 500},
        },
    )
    cache_path = tmp_path / "preflight.json"

    working, results = preflight_scan_markets(
        ["BTC", "KM:GOOGL", "FLX:OIL", "ETH"], cache_path=cache_path, http_post=post
    )

    assert working == ["BTC", "xyz:GOOGL", "ETH"]
    excluded = [r.raw for r in results if not r.working_entry]
    assert excluded == ["FLX:OIL"]
