# CLAUDE.md — Trading Agent

## Projekt-Übersicht

Regelbasierter Python Trading Agent für die Prop-Trading-Plattform **Propr**.
Strategie: Bollinger Bands + MACD-Regime (bullish / bearish / neutral).
Echtzeit-Marktdaten kommen von **Hyperliquid** (REST, perspektivisch WebSocket).
Gelieferte Kerzenreihen werden pro Provider durch [`data/providers/contract.py`](data/providers/contract.py) geprüft (UTC, streng aufsteigende Zeitstempel, Mindestlänge bei Golden).
Execution läuft ausschließlich über die **Propr API**.

---

## Architektur-Schichten

```
app/            # trading_app.py, journal.py, risk_guard.py
strategy/       # agent_cycle, decision_engine, signal_rules, regime_detector,
                # trend_signal_detector, countertrend_signal_detector,
                # position_sizer, order_manager, trade_manager, strategy_runner, state, engine
broker/         # alle Propr-API-Integration (propr_client, propr_sdk, execution, order_service,
                # state_sync, symbol_service, health_guard, asset_guard, challenge_service, propr_ws);
                # offizielles SDK: PyPI-Paket propr_sdk, geladen über broker/propr_sdk.py
config/         # propr_config.py, hyperliquid_config.py, strategy_config.py
indicators/     # bollinger.py, macd.py (Indikator-Implementierungen)
models/         # Datenmodelle: candle, decision, order, regime, signal, symbol_spec, trade, ...
deploy/         # Deployment-Artefakte; deploy/raspberry_pi/managed_runner.py (Haupt-Runner)
ha_addons/      # Home Assistant Add-on Dateien
scripts/        # manuelle Test- und Run-Skripte
utils/          # env_loader, runtime_status, runtime_overrides, journal_snapshot,
                # http_client, journal_table, live_status, operator_config, run_summary
tests/          # pytest-basiert, Golden Fixtures
artifacts/      # Journal, Status, Logs (nicht committen)
```

**Normative Architektur (Schichten, Datenfluss, Safety-Invarianten, PR-Checkliste):** [docs/ARCHITECTURE_MANIFEST.md](docs/ARCHITECTURE_MANIFEST.md) — zentrales Dokument, gegen das Entwürfe und Diffs geprüft werden; CLAUDE.md bleibt der operative Leitfaden (Setup, Env, Tests).

---

## Development Setup

```bash
# Python-Umgebung (Windows, Netzlaufwerk)
.\.venv\Scripts\python.exe <script>

# Tests laufen lassen
.\.venv\Scripts\pytest tests/

# Alle Golden-Szenarien prüfen
.\.venv\Scripts\python.exe scripts/run_all_golden_scenarios.py
```

Abhängigkeiten: `pandas`, `numpy`, `pydantic`, `python-dotenv`, `pytest`, `requests`, `python-ulid`, `websockets`

---

## Kritische Sicherheitsregeln

**Beta ist der sichere Default. Prod-Writes sind mehrfach abgesichert.**

- `PROPR_ENV=beta` immer beim Entwickeln und Testen
- `PROPR_ENV=prod` ist nur wirksam, wenn zusätzlich `PROPR_PROD_CONFIRM=YES` in `.env` gesetzt ist
- Echter Submit braucht explizite Confirm-Flags:
  - Scripts: `MANUAL_ALLOW_SUBMIT=YES`
  - Runner: `RUNNER_ALLOW_SUBMIT=YES`
  - Scanner: `SCAN_ALLOW_SUBMIT=YES`
- Im `DATA_SOURCE=golden`-Modus ist Submit **hart blockiert**, egal welche Flags gesetzt sind
- **Niemals** `PROPR_PROD_CONFIRM=YES` in Code-Änderungen oder Beispielen setzen

---

## Wichtige Konventionen

- **Decimal** für alle mengen- und preisbezogenen Werte im Broker-Layer (nicht float)
- **ULID** als `intentId` für jede neue Order (`python-ulid`)
- HTTP `200` und `201` gelten beide als Erfolg bei Create/Cancel
- Positionen mit `quantity == 0` werden beim State-Sync nicht als aktive Trades übernommen
- Quantity-Rundung: immer auf Basis `quantity_decimals` aus SymbolSpec
- Preis-Rundung: nur wenn `price_decimals` verfügbar — sonst Wert unverändert lassen
- Echter Live-Submit wird blockiert, wenn keine SymbolSpec geladen werden kann

---

## Env-Variablen (Kurzreferenz)

| Variable | Bedeutung |
|---|---|
| `PROPR_ENV` | `beta` oder `prod` |
| `PROPR_BETA_*` / `PROPR_PROD_*` | API-Credentials je Umgebung |
| `PROPR_SYMBOL` | z.B. `BTC` oder `xyz:AAPL` (Legacy: `BTC/USDC` akzeptiert) |
| `PROPR_LEVERAGE` | gewünschte Leverage (Fallback: `x1`) |
| `PROPR_PROD_CONFIRM` | `YES` nötig für Prod-Zugriff |
| `DATA_SOURCE` | `live` oder `golden` |
| `GOLDEN_SCENARIO` | exakter Szenario-Name (nur bei `golden`) |
| `HYPERLIQUID_COIN` | optional; überschreibt den aus `PROPR_SYMBOL` abgeleiteten HL-Coin (`BTC`/`ETH`; bei HIP-3 sonst automatisch `xyz:TICKER`) |
| `TRADING_JOURNAL_PATH` | optional, überschreibt Standardpfad |
| `RUNNER_STATUS_PATH` | optional, überschreibt Standardpfad |
| `TRADING_AGENT_RUNTIME_CONFIG_PATH` | optional, überschreibt Standardpfad |
| `TRADING_AGENT_LIVE_STATUS_PATH` / `OPERATOR_LIVE_STATUS_PATH` | optional, Ziel für `live_status.json` (REST-Sync, WS-Daemon, HA-Panel) |
| `PROPR_REQUIRE_HEALTHY_CORE` | `YES`/`NO` für Core-Health-Guard |
| `PROPR_STABLE_INTENT_ID` | optional `YES`: Pending-Entry-Submits nutzen deterministisches `intentId` aus Seed (`build_order_submission_preview`); nur nach Abgleich mit Propr-Idempotenz-Verhalten aktivieren |

---

## Test-Strategie

- **Unit-Tests**: `tests/` mit pytest, keine echten API-Calls
- **Golden Scenarios**: fachliche Fixtures für alle Signaltypen — deterministisch, kein Submit
- **Smoke Test**: read-only gegen Beta-API (`scripts/propr_smoke_test.py`)
- **Write Test**: Beta-Submit + direkter Cancel (`scripts/propr_submit_cancel_test.py`)
- **Order Types Test**: Beta-Verifikation aller Order-Typen (`scripts/propr_order_types_test.py`) — inkl. Versuch standalone `BUY_STOP`/`SELL_STOP`; bei Erfolg primär WebSocket-Bestätigung (orders), sonst REST-Fallback; bei Ablehnung 13056 wird übersprungen und der Lauf setzt fort
- **Run Suite**: `python run_test_suite.py --suite <name>` — verfügbare Suites:
  - `core` — fokussierter Regressionstest (Bot-Logik + Runtime-Helpers)
  - `unit` — vollständige pytest-Suite unter `tests/`
  - `preflight` — empfohlener Erststarttest: unit + golden dry-run + smoke test *(Standard für Pi/HA)*
  - `beta_write` — Beta-Write-Verifikation mit echten Orders (opt-in, `--allow-live-beta-writes`)

Bekannte Beta-Einschränkung: `BUY_STOP` / `SELL_STOP` als standalone Entry werden von der Propr-API mit `conditional_order_requires_position_or_group` (HTTP 400, Code 13056) abgelehnt — unabhängig davon, dass `orderGroupId` in Responses oft `null` ist. Der Agent blockiert diese Submits auf Beta weiterhin vorab (`trading_app`), damit keine nutzlosen API-Fehlschläge entstehen.

---

## Signal-Logik (Kurzübersicht)

- **Trend-Signale**: nur in `bullish` oder `bearish`, innerhalb max. Regime-Alter, Schlusskurs tief genug in relevanter BB-Hälfte
- **Gegentrend-Signale**: in allen Regimen möglich
  - In `bullish`/`bearish`: nur auf dem ersten Bar des Regimes (First-Bar-Regel)
  - In `neutral`: Richtung aus Outside-Fall (oberhalb oberes Band → SHORT, unterhalb unteres Band → LONG)
  - Pro Regime und Richtung maximal ein valides Gegentrend-Signal
- PineScript-Verifier: `artifacts/tradingview_strategy_indicator.pine`

---

## Runtime-Betrieb (Raspberry Pi / Greenbox)

- Managed Runner: `python managed_runner.py` (Root-Wrapper → `deploy/raspberry_pi/managed_runner.py`) — schreibt Status-JSON für Monitoring
- **Live-Status WebSocket** (PnL / offene Positionen in `live_status.json`): separates Long-Running-Skript `scripts/ws_live_status_daemon.py` — gleiche `.env` wie Propr, gemeinsamer Pfad via `TRADING_AGENT_LIVE_STATUS_PATH` oder `TRADING_AGENT_DATA_PATH` (siehe Docstring; typisch zweite systemd-Unit auf dem Pi)
- systemd-Service: `trading-agent.service.example` als Vorlage
- Home Assistant: liest Status + Journal per SSH, steuert Start/Stop/Restart
- Runtime-Overrides (ohne `.env` anzufassen): `python runtime_config.py set ...`
- Standardpfade Artifacts: `artifacts/runner_status_{env}.json`, `artifacts/trading_journal_{env}.jsonl`

---

## Multi-Market-Scan

- `SCAN_MARKETS=BTC,ETH,SOL` — einfache Ticker (neues Format)
- HIP-3 Assets: `SCAN_MARKETS=BTC,ETH,xyz:AAPL` — `xyz:`-Prefix für Stocks/Commodities; für **Hyperliquid**-Kerzen/L2 wird derselbe dex-qualifizierte Name (`xyz:AAPL`) verwendet, nicht nur `AAPL`
- Legacy-Format `BTC/USDC:BTC,ETH/USDC:ETH` wird noch akzeptiert (mit Deprecation-Warnung)
- Max. 3 offene Entry-Orders oder Positionen kontoweit
- Priorisierung nach `signal_strength` wenn mehr Kandidaten als freie Slots
- Asset Registry: `broker/asset_registry.py` — auto-discovers tradeable assets from Hyperliquid, caches to `artifacts/asset_registry.json` (24h TTL)
- Live (`DATA_SOURCE=live`): Vor dem Kerzenabruf ruft `scripts/multi_market_scan.py` `AssetRegistry.validate_scan_asset_for_hyperliquid_fetch` — Krypto-Perps gegen die HL-Meta-Liste, HIP-3-Einträge gegen die Registry (`xyz:…`); leere Universe-Listen (offline) → nur Log-Warnung, keine harte Prüfung.
- Journal (Scan): Schlägt ein Markt vor `run_app_cycle` fehl, wird eine **cycle**-Zeile angehängt (`scan_cycle_phase=scan_failed`, `skipped_reason=scan_failed`, Fehlertext in `notes`). Dry-Run und Execute eines Laufs teilen sich `executed_at`; die Scan-Aggregation in `utils/journal_table.py` dedupliziert zugehörige **cycle**-Zeilen pro Batch (bei Konflikt gewinnt `execute` vor `dry_run`).

---

## Was nicht committet werden soll

- `.env` (Credentials)
- `artifacts/` (Journal, Status, Logs)
- `__pycache__/`
