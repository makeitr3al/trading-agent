from __future__ import annotations

import argparse
import json

from utils.runtime_overrides import (
    SUPPORTED_RUNTIME_OVERRIDE_KEYS,
    get_effective_runtime_value,
    load_runtime_overrides,
    resolve_runtime_overrides_path,
    update_runtime_overrides,
)


def _validate_propr_env(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"beta", "prod"}:
        raise ValueError("PROPR_ENV must be beta or prod")
    return normalized


def _validate_symbol(value: str) -> str:
    from utils.asset_normalizer import normalize_asset
    info = normalize_asset(value)
    return info.asset


def _validate_leverage(value: int) -> str:
    if value < 1:
        raise ValueError("PROPR_LEVERAGE must be greater than or equal to 1")
    return str(int(value))


def _validate_scan_markets(value: str) -> str:
    from utils.asset_normalizer import parse_market_list
    infos = parse_market_list(value)
    return ",".join(info.asset for info in infos)


def _effective_payload() -> dict[str, object]:
    override_path = resolve_runtime_overrides_path()
    overrides = load_runtime_overrides(path=override_path)
    effective = {key: get_effective_runtime_value(key) or None for key in SUPPORTED_RUNTIME_OVERRIDE_KEYS}
    return {
        "override_path": str(override_path),
        "overrides_active": bool(overrides),
        "overrides": overrides,
        "effective": effective,
    }


def _print_payload(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage runtime overrides for Home Assistant driven bot configuration.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("show", help="Print current effective runtime configuration as JSON.")

    set_parser = subparsers.add_parser("set", help="Set one or more runtime override values.")
    set_parser.add_argument("--propr-env")
    set_parser.add_argument("--propr-symbol")
    set_parser.add_argument("--propr-leverage", type=int)
    set_parser.add_argument("--scan-markets")

    clear_parser = subparsers.add_parser("clear", help="Clear one or more runtime override values.")
    clear_parser.add_argument("--all", action="store_true")
    clear_parser.add_argument("--propr-env", action="store_true")
    clear_parser.add_argument("--propr-symbol", action="store_true")
    clear_parser.add_argument("--propr-leverage", action="store_true")
    clear_parser.add_argument("--scan-markets", action="store_true")

    args = parser.parse_args()

    try:
        if args.command == "show":
            _print_payload(_effective_payload())
            return 0

        if args.command == "set":
            updates: dict[str, str] = {}
            if args.propr_env is not None:
                updates["PROPR_ENV"] = _validate_propr_env(args.propr_env)
            if args.propr_symbol is not None:
                updates["PROPR_SYMBOL"] = _validate_symbol(args.propr_symbol)
            if args.propr_leverage is not None:
                updates["PROPR_LEVERAGE"] = _validate_leverage(args.propr_leverage)
            if args.scan_markets is not None:
                updates["SCAN_MARKETS"] = _validate_scan_markets(args.scan_markets)

            if not updates:
                raise ValueError("No runtime override values were provided")

            path, overrides = update_runtime_overrides(updates)
            _print_payload(
                {
                    "status": "updated",
                    "override_path": str(path),
                    "overrides": overrides,
                    "effective": _effective_payload()["effective"],
                }
            )
            return 0

        clear_keys: list[str] = []
        if args.all:
            clear_keys = list(SUPPORTED_RUNTIME_OVERRIDE_KEYS)
        else:
            if args.propr_env:
                clear_keys.append("PROPR_ENV")
            if args.propr_symbol:
                clear_keys.append("PROPR_SYMBOL")
            if args.propr_leverage:
                clear_keys.append("PROPR_LEVERAGE")
            if args.scan_markets:
                clear_keys.append("SCAN_MARKETS")

        if not clear_keys:
            raise ValueError("No runtime override keys were selected for clearing")

        path, overrides = update_runtime_overrides({}, clear_keys=clear_keys)
        _print_payload(
            {
                "status": "cleared",
                "override_path": str(path),
                "overrides": overrides,
                "effective": _effective_payload()["effective"],
            }
        )
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
