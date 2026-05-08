"""Preflight validation of SCAN_MARKETS against Hyperliquid ``/info``.

For each user-listed market entry, probe Hyperliquid ``/info`` to find a working
coin form by trying prefix variants in order:

1. The raw entry as configured (e.g. ``KM:GOOGL`` or ``xyz:MSTR`` or ``BTC``)
2. ``xyz:<BASE>`` for non-HIP-3 raw entries (``KM:GOOGL`` → ``xyz:GOOGL``)
3. The bare base ticker (``KM:GOOGL`` → ``GOOGL``, ``xyz:MSTR`` → ``MSTR``)

A market is considered "working" when both ``l2Book`` and ``candleSnapshot``
return HTTP 200 with non-empty/valid bodies. The first working candidate wins.
If no candidate works, the entry is excluded from the active scan list.

Results are cached on disk with a 24 h TTL (configurable) so a daily scan does
not re-probe HL on every cycle. Cache lives at ``TRADING_AGENT_DATA_PATH`` /
``scan_market_preflight.json`` by default and can be overridden via
``SCAN_PREFLIGHT_CACHE_PATH``. Set ``SCAN_PREFLIGHT_DISABLED=YES`` to bypass
preflight entirely (useful for offline tests).
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Sequence

import requests

from utils.asset_normalizer import normalize_asset


HL_INFO_URL = "https://api.hyperliquid.xyz/info"
DEFAULT_CACHE_NAME = "scan_market_preflight.json"
DEFAULT_TTL_HOURS = 24
DEFAULT_PROBE_INTERVAL = "1d"
DEFAULT_PROBE_LOOKBACK_DAYS = 3


HttpPostFn = Callable[[dict], "requests.Response"]


@dataclass(frozen=True)
class PreflightResult:
    raw: str
    working_entry: str | None
    reason: str | None  # populated only when working_entry is None


def _resolve_cache_path() -> Path:
    explicit = (os.getenv("SCAN_PREFLIGHT_CACHE_PATH") or "").strip()
    if explicit:
        return Path(explicit)
    data_path = (os.getenv("TRADING_AGENT_DATA_PATH") or "artifacts").strip() or "artifacts"
    return Path(data_path) / DEFAULT_CACHE_NAME


def _ttl_hours_from_env() -> int:
    raw = (os.getenv("SCAN_PREFLIGHT_TTL_HOURS") or "").strip()
    try:
        v = int(raw) if raw else DEFAULT_TTL_HOURS
    except ValueError:
        v = DEFAULT_TTL_HOURS
    return max(1, v)


def is_preflight_disabled() -> bool:
    raw = (os.getenv("SCAN_PREFLIGHT_DISABLED") or "").strip().upper()
    return raw == "YES"


def _candidate_entries(raw: str) -> list[str]:
    """Return ordered, deduplicated prefix variants for a raw market entry.

    Examples:
        "BTC"        -> ["BTC", "xyz:BTC"]
        "xyz:MSTR"   -> ["xyz:MSTR", "MSTR"]
        "KM:GOOGL"   -> ["KM:GOOGL", "xyz:GOOGL", "GOOGL"]
        "FLX:OIL"    -> ["FLX:OIL", "xyz:OIL", "OIL"]
    """
    info = normalize_asset(raw)
    raw_trim = (raw or "").strip()
    out: list[str] = []

    def _add(candidate: str) -> None:
        c = (candidate or "").strip()
        if c and c not in out:
            out.append(c)

    _add(raw_trim)

    if ":" in raw_trim:
        # Take the segment after the last colon: handles "xyz:MSTR", "KM:GOOGL", "FLX:OIL".
        bare = raw_trim.split(":")[-1].strip().upper()
    else:
        bare = (info.base or "").upper()

    if bare:
        if not info.is_hip3:
            _add(f"xyz:{bare}")
        _add(bare)
    return out


def _http_post_info(payload: dict) -> "requests.Response":
    return requests.post(HL_INFO_URL, json=payload, timeout=15)


def _probe_one(coin: str, *, http_post: HttpPostFn | None = None) -> tuple[bool, str]:
    """Return (success, reason). Success requires both l2Book and candleSnapshot OK."""
    post: HttpPostFn = http_post or _http_post_info

    try:
        l2_resp = post({"type": "l2Book", "coin": coin})
    except Exception as exc:
        return False, f"l2Book network: {exc.__class__.__name__}: {exc}"
    l2_status = getattr(l2_resp, "status_code", 0)
    if l2_status != 200:
        return False, f"l2Book HTTP {l2_status}"
    try:
        l2_body = l2_resp.json()
    except Exception:
        return False, "l2Book invalid JSON"
    if not isinstance(l2_body, dict):
        return False, "l2Book body not dict"
    levels = l2_body.get("levels")
    if (
        not isinstance(levels, list)
        or len(levels) < 2
        or not isinstance(levels[0], list)
        or not isinstance(levels[1], list)
        or not levels[0]
        or not levels[1]
    ):
        return False, "l2Book empty levels"

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (DEFAULT_PROBE_LOOKBACK_DAYS * 24 * 60 * 60 * 1000)
    try:
        c_resp = post(
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": coin,
                    "interval": DEFAULT_PROBE_INTERVAL,
                    "startTime": start_ms,
                    "endTime": end_ms,
                },
            }
        )
    except Exception as exc:
        return False, f"candleSnapshot network: {exc.__class__.__name__}: {exc}"
    c_status = getattr(c_resp, "status_code", 0)
    if c_status != 200:
        return False, f"candleSnapshot HTTP {c_status}"
    try:
        c_body = c_resp.json()
    except Exception:
        return False, "candleSnapshot invalid JSON"
    if not isinstance(c_body, list) or not c_body:
        return False, "candleSnapshot empty list"
    return True, "ok"


def _resolve_one(raw: str, *, http_post: HttpPostFn | None = None) -> PreflightResult:
    last_reason: str | None = "no_candidate"
    for cand in _candidate_entries(raw):
        ok, reason = _probe_one(cand, http_post=http_post)
        if ok:
            return PreflightResult(raw=raw, working_entry=cand, reason=None)
        last_reason = f"{cand}: {reason}"
    return PreflightResult(raw=raw, working_entry=None, reason=last_reason)


def _load_cache(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _save_cache(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def preflight_scan_markets(
    raw_assets: Sequence[str],
    *,
    cache_path: Path | None = None,
    ttl_hours: int | None = None,
    http_post: HttpPostFn | None = None,
    now_utc: datetime | None = None,
) -> tuple[list[str], list[PreflightResult]]:
    """Resolve raw scan-market entries to HL-working forms; cache results.

    Returns ``(working_entries, all_results)``. ``working_entries`` preserves input
    order and contains only entries with a working coin (the resolved form, which
    may differ from the raw entry when a different prefix was needed).
    """
    cache_p = cache_path or _resolve_cache_path()
    ttl = ttl_hours if ttl_hours is not None else _ttl_hours_from_env()
    now = now_utc or datetime.now(timezone.utc)
    expiry_threshold = now - timedelta(hours=ttl)

    cache = _load_cache(cache_p)
    out_results: list[PreflightResult] = []
    out_working: list[str] = []
    cache_dirty = False

    for raw in raw_assets:
        raw_key = (raw or "").strip()
        if not raw_key:
            continue
        cache_entry = cache.get(raw_key)
        cached_at = _parse_iso(cache_entry.get("checked_at")) if isinstance(cache_entry, dict) else None
        use_cache = isinstance(cache_entry, dict) and cached_at is not None and cached_at > expiry_threshold
        if use_cache:
            assert isinstance(cache_entry, dict)
            result = PreflightResult(
                raw=raw_key,
                working_entry=cache_entry.get("working_entry"),
                reason=cache_entry.get("reason"),
            )
        else:
            result = _resolve_one(raw_key, http_post=http_post)
            cache[raw_key] = {
                "raw": raw_key,
                "working_entry": result.working_entry,
                "reason": result.reason,
                "checked_at": now.isoformat(),
            }
            cache_dirty = True

        out_results.append(result)
        if result.working_entry:
            out_working.append(result.working_entry)
        else:
            print(
                f"[preflight] excluded raw={raw_key!r} reason={result.reason}",
                file=sys.stderr,
                flush=True,
            )

    if cache_dirty:
        _save_cache(cache_p, cache)

    excluded_count = len(out_results) - len(out_working)
    if excluded_count > 0:
        excluded = [r.raw for r in out_results if not r.working_entry]
        print(
            f"[preflight] {excluded_count} market(s) excluded from scan: {','.join(excluded)}",
            file=sys.stderr,
            flush=True,
        )
    return out_working, out_results
