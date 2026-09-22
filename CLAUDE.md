# CLAUDE.md — Trading Agent

## Projekt-Übersicht

Regelbasierter Python Trading Agent für die Prop-Trading-Plattform **Propr**.
Strategie: Bollinger Bands + MACD-Regime (bullish / bearish / neutral).
Echtzeit-Marktdaten kommen von **Hyperliquid** (REST, perspektivisch WebSocket).
Gelieferte Kerzenreihen werden pro Provider durch [`data/providers/contract.py`](data/providers/contract.py) geprüft (UTC, streng aufsteigende Zeitstempel, Mindestlänge bei Golden).
Execution läuft ausschließlich über die **Propr API**.

**Normative API-Dokumentation (neben diesem Repo):** [XBorgLabs/propr-docs](https://github.com/XBorgLabs/propr-docs) — REST-Referenz in `docs/api.md`, Referenz-SDKs unter `python/` und `javascript/`. Änderungen an Order-Payloads, Batch-Regeln (`orderGroupId`, Conditional Orders) oder Fehlercodes sollten gegen diese Doku verifiziert werden; der Vendored-Client [`broker/propr_sdk.py`](broker/propr_sdk.py) und [`broker/propr_client.py`](broker/propr_client.py) (`_to_sdk_order_payload`) können hinter der offiziellen Spezifikation nachziehen.

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
backtest/       # Offline-Simulation/Screening (kein Submit): daily_universe, screener,
                # metrics, propr_exchange_assets (öffentlicher Propr-Catalog, ohne API-Key)
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
- **Kein Pyramiding:** Solange Propr für das Symbol eine offene Position meldet (`AgentState.has_open_broker_position_for_symbol` oder frischer `/positions`-Check), sendet der Bot **kein** neues Entry/bracket — auch wenn keine SL/TP aus dem REST-Snapshot auf eine `Trade`-Zeile gemappt werden können. Blockierung mit klarem `skipped_reason` im Journal (`submit blocked: open position present at broker for symbol` bzw. bei Trend-Trigger `open position present at broker for symbol`).

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
| `TREND_STOP_TRIGGER_MODE` | `last_candle` (Default), `ws`, oder `disabled`. `last_candle`: OHLC-Poll → Market-Bracket. `ws`: Hyperliquid-Trades-Watcher im Trigger-Daemon. `disabled`: kein Auto-Submit |
| `TREND_STOP_MAX_GAP_R_RATIO` | Max. Overshoot past Entry als Anteil von \|Entry−SL\| (Default `0.5`); bei Überschreitung Skip + Disarm. `OFF` deaktiviert den Gap-Guard |
| `JOURNAL_BAR_DEDUPE` | `YES`/`NO` (Default: `YES`); dedupliziert Journal-Emissionen innerhalb derselben Signal-Bar bei Interval-Runs |

---

## Test-Strategie

- **Unit-Tests**: `tests/` mit pytest, keine echten API-Calls
- **Golden Scenarios**: fachliche Fixtures für alle Signaltypen — deterministisch, kein Submit
- **Smoke Test**: read-only gegen Beta-API (`scripts/propr_smoke_test.py`)
- **Write Test**: Beta-Submit + direkter Cancel (`scripts/propr_submit_cancel_test.py`)
- **Order Types Test**: Beta-Verifikation aller Order-Typen (`scripts/propr_order_types_test.py`) — inkl. Versuch **standalone** `BUY_STOP`/`SELL_STOP` (ohne Batch); bei Erfolg primär WebSocket-Bestätigung (orders), sonst REST-Fallback; bei Ablehnung 13056 wird übersprungen und der Lauf setzt fort *(Bot-Entry nutzt dagegen Bracket-Batch mit `orderGroupId`)*
- **Run Suite**: `python run_test_suite.py --suite <name>` — verfügbare Suites:
  - `core` — fokussierter Regressionstest (Bot-Logik + Runtime-Helpers)
  - `unit` — vollständige pytest-Suite unter `tests/`
  - `preflight` — empfohlener Erststarttest: unit + golden dry-run + smoke test *(Standard für Pi/HA)*
  - `beta_write` — Beta-Write-Verifikation mit echten Orders (opt-in, `--allow-live-beta-writes`)
- **Daily Universe Backtest** (Hyperliquid 1D, offline, kein Submit): `scripts/backtest_daily_universe.py` — siehe Abschnitt **Daily Universe Backtest** unten
- **Market Profitability Screener** (Propr-Whitelist ∩ HL-1D, GO/NO_GO): `scripts/backtest_market_screener.py` — siehe Abschnitt **Market Profitability Screener** unten

**Propr-API (Entry-Orders):** In der Batching-Logik gilt **nur** `market` oder `limit` als **Entry-Order**. Stop-Entries (`BUY_STOP`/`SELL_STOP` → API `stop_limit`) sind **conditional orders** und werden ohne `positionId` bzw. ohne Entry-Order in derselben `orderGroupId` mit `conditional_order_requires_position_or_group` (HTTP 400, Code 13056) abgelehnt. Der Bot blockiert solche Stop-Entry-Submits deshalb **vorab** in `broker/execution.py` mit einem klaren `skip_reason`.

**Workaround (Virtual Stop):** Trend- und Gegentrend-Signale erzeugen intern weiterhin `BUY_STOP`/`SELL_STOP` als `pending_order` (Strategie-Semantik bleibt gleich). Live wird der Stop **nicht** als resting Stop-Order an Propr gesendet. State-Sync erhält broker-lose Stop-Intents. Submit läuft über `app/armed_stop_submit.execute_armed_stop_market_bracket` (Market-Bracket).

Auslöser (`TREND_STOP_TRIGGER_MODE`):
- `last_candle` (Default): Last-Candle High/Low im Cycle / 60s-Poll
- `ws`: Hyperliquid `trades` WebSocket im `scripts/trigger_polling_daemon.py` (Last Print ≥/≤ Entry); Kerzengrenze macht Catch-up auf dem eingefrorenen Level, danach Strategy-Refresh/Cancel. Universum-Scan bleibt `OPERATOR_SCHEDULE_TIME`
- `disabled`: kein Auto-Submit

Gap-Guard: `TREND_STOP_MAX_GAP_R_RATIO` (Default `0.5`). Live setzt `run_agent_cycle(..., synthesize_local_fills=False)`, damit kein lokales `active_trade` ohne Propr-Fill entsteht.

Env-Schalter:
- `TREND_STOP_TRIGGER_MODE=last_candle|ws|disabled` (Default: `last_candle`)
- `TREND_STOP_MAX_GAP_R_RATIO=0.5|OFF` (Default: `0.5`)
- `JOURNAL_BAR_DEDUPE=YES|NO` (Default: `YES`)

Der Bot sendet **Bracket-Entries** (Entry + Exits) als **einen** `create_orders`-Batch (`ProprClient.create_orders_batch_raw`): Entry (`market` oder `limit`) + Stop (`stop_market`) + TP (`take_profit_limit`) unter gemeinsamem `orderGroupId` (`broker/order_service.submit_bracket_entry_with_exits`). Beim Live-State-Sync reichert `sync_agent_state_from_propr` Positionszeilen zuerst mit SL/TP aus verknüpften Orders an; liefert der strenge Position-Mapper (`map_propr_position_to_internal`) danach kein `Trade` (benötigt u. a. `stop_loss`), kann `build_agent_state_from_propr_data` für **genau eine** offene Position auf dem Symbol `active_trade` aus **vorherigem** `AgentState` synthetisieren (`pending_order` oder `active_trade`, Richtung passend), damit Exit-Management greift.

---

## Daily Universe Backtest (Hyperliquid 1D)

Offline-Screening über viele HL-Märkte mit **unabhängigem Kapital pro Markt**. Kerzen: `1d` via `data/providers/hyperliquid_historical_provider.py` (`fetch_candles_between` + Jahresfenster-Chunking + Cache unter `artifacts/backtests/cache/`). Logik pro Bar: **`run_agent_cycle`** (Pending-Fills wie live) plus **Intrabar SL/TP** auf Daily-OHLC (Default: bei gleichzeitigem Touch **SL vor TP**, Sensitivity mit `--optimistic-fills`). Strategische Exits (`CLOSE_*`) werden am **Bar-Close** ausgeführt, wenn der Cycle `close_active_trade` setzt.

**Beispiel (nur Krypto-Perps, Shard 0/4, 3 Jahre, 10k pro Markt):**

```bash
.\.venv\Scripts\python.exe scripts/backtest_daily_universe.py --years 3 --capital 10000 --include crypto --shard 0/4 --sleep-ms 300
```

Ausgabe: `artifacts/backtests/daily_universe_<UTC>/summary.csv`, optional `…/<coin>/trades.csv`, `run.json` mit Parametern und Annahmen.

**Wichtige Annahmen / Grenzen:** HL-Kerzen ≠ Propr-Ausführung; im Strategiecode sind Trend-Entries `BUY_STOP`/`SELL_STOP`, live gehen Bracket-Entries als Limit-Batch an Propr — der Backtest misst die **Strategie-Trigger-Semantik** auf HL-Daten. Kein Funding, kein intraday außerhalb der 1D-OHLC. `--no-compound` hält das Sizing-Risiko auf dem Startkapital statt auf der laufenden Equity.

---

## Market Profitability Screener

Research-Pipeline über die **Propr-Whitelist** der gewählten Umgebung (öffentlicher Catalog `GET …/v1/exchange-assets/config/hyperliquid`, Base folgt `PROPR_ENV` / `--propr-env`; **kein API-Key**, kein Submit). Implementierung: `scripts/backtest_market_screener.py` plus `backtest/propr_exchange_assets.py` (Catalog), `backtest/screener.py` (End-MTM, Jahres-Stabilität, GO/NO_GO), `backtest/metrics.py` (Calmar-Ranking). Kerzen weiterhin Hyperliquid 1D über `backtest/daily_universe.py`. Pro Markt **eine** kontinuierliche Simulation (`run_agent_cycle`: Trend + Gegentrend), dann End-MTM offener Positionen, Gates und Ranking. Kein Auto-Export nach `SCAN_MARKETS`.

**Beispiel (5 Jahre, Beta-Catalog, Shard 0/4):**

```bash
.\.venv\Scripts\python.exe scripts/backtest_market_screener.py --years 5 --capital 10000 --shard 0/4 --sleep-ms 300
```

Offline-Catalog: `--propr-assets-file path/to/snapshot.json` (oder Cache `artifacts/backtests/propr_exchange_assets_{env}.json`). Shard-Merge:

```bash
.\.venv\Scripts\python.exe scripts/backtest_screener_merge.py artifacts/backtests/screener_*/summary.csv --out artifacts/backtests/screener_merged
```

Ausgabe unter `artifacts/backtests/screener_<UTC>/`: `summary.csv`, `shortlist.csv` (nur `GO`), `report.md`, `run.json`. Defaults: kein Compound, Slippage 5 bps, Fees `2×taker` aus dem Catalog, `min_trades` 8, `max_dd` 35 %, Profit-Faktor ≥ 1.2, `year_pass_rate` ≥ 0.5, `min_active_years` 2, `min_history_coverage` 0.80, positives Recent-12m-Fenster (`min_trades_recent` 2). Entscheidungen: `GO` / `NO_GO` / `INSUFFICIENT_DATA` / `SKIPPED`. Ranking: Calmar ↓, dann Return% ↓, dann `n_trades` ↓.

---

## Signal-Logik (Kurzübersicht)

- **Trend-Signale**: nur in `bullish` oder `bearish`, innerhalb max. Regime-Alter, Schlusskurs tief genug in relevanter BB-Hälfte
- **Gegentrend-Signale**: in allen Regimen möglich
  - In `bullish`/`bearish`: nur auf dem ersten Bar des Regimes (First-Bar-Regel)
  - In `neutral`: Richtung aus Outside-Fall (oberhalb oberes Band → SHORT, unterhalb unteres Band → LONG)
  - Pro Regime und Richtung maximal ein valides Gegentrend-Signal
- **Offenes Gegentrend-Trade-Management**: Take-Profit folgt dem mBB der **letzten geschlossenen** Kerze (dieselbe Closed-Bar-Ansicht wie die Signalerkennung: DataFrame `bollinger_sig` in `strategy_runner.run_strategy_cycle`), nicht dem Tick einer noch formenden Kerze.
- **Entry-Gating (Signals vs Orders)**: Signale koennen valide sein, waehrend die per-cycle Orchestrierung die **Order-Erzeugung** aus Safety-Gruenden blockiert (z. B. Middle-Band-Retest-Gating) und dann `NO_ACTION` entscheidet; Details dazu stehen im Journal auf der cycle-Zeile als kompakter `decision_detail` in `notes`.
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

## Home Assistant Add-on: Trigger-Polling (Long-Running)

Wenn das HA Add-on im `mode=scharf` laeuft und `trigger_polling_enabled=true` ist (Operator-Config), startet `ha_addons/trading_agent/run.sh` statt dem one-shot Scan einen Daemon:

- **Entrypoint:** `scripts/trigger_polling_daemon.py`
- **Scan:** taeglich um `OPERATOR_SCHEDULE_TIME` (Default `07:00` UTC) ein Vollscan (Dry-Run + Execute non-stop Pendings).
- **Armed Watch:** Maerkte mit Stop-Pending-Intent (`pending_order.order_type ∈ {BUY_STOP, SELL_STOP}`).
  - `TREND_STOP_TRIGGER_MODE=last_candle` (Default): Poll alle ~60s (OHLC via `run_app_cycle` / `_phase_pending_trigger`) plus Kerzengrenzen-Catch-up/Refresh.
  - `TREND_STOP_TRIGGER_MODE=ws`: Hyperliquid-Trades-WebSocket (Last Print) plus Kerzengrenzen-Catch-up/Refresh; bei WS-Ausfall Fallback auf OHLC-Poll.
  - Gap-Guard: `TREND_STOP_MAX_GAP_R_RATIO` (Default `0.5`; `OFF` deaktiviert).
- **Persistenz:** `/share/trading-agent-data/armed_stop_markets.json` + `agent_state_<symbol>.json` (pro Markt); Sync loescht broker-lose Stops nicht mehr (`_resolve_local_virtual_stop_pending`).
- **Heartbeat:** schreibt in `RUNNER_STATUS_PATH` (`runtime_status_<env>.json`) regelmaessig `runner_state`, `armed_markets_count`, `last_poll_tick_at`, `last_scan_at`.

---

## Multi-Market-Scan

- `SCAN_MARKETS=BTC,ETH,SOL` — einfache Ticker (neues Format)
- HIP-3 Assets: `SCAN_MARKETS=BTC,ETH,xyz:AAPL` — `xyz:`-Prefix für Stocks/Commodities; für **Hyperliquid**-Kerzen/L2 wird derselbe dex-qualifizierte Name (`xyz:AAPL`) verwendet, nicht nur `AAPL`
- Legacy-Format `BTC/USDC:BTC,ETH/USDC:ETH` wird noch akzeptiert (mit Deprecation-Warnung)
- Max. 3 offene Entry-Orders oder Positionen kontoweit
- Priorisierung nach `signal_strength` wenn mehr Kandidaten als freie Slots
- Asset Registry: `broker/asset_registry.py` — auto-discovers tradeable assets from Hyperliquid (inkl. zusätzlicher Perp-DEXes), cachet nach `artifacts/asset_registry.json` (24h TTL). Klassifikation: `crypto`, `builder_perp` (z. B. `xyz:EUR`), `hip3` (Stocks/Commodities), optional `backend_coin` (nur „gesehen“ via `allMids`, nicht garantiert candle-/tradebar).
- Live (`DATA_SOURCE=live`): Vor dem Kerzenabruf ruft `scripts/multi_market_scan.py` `AssetRegistry.validate_scan_asset_for_hyperliquid_fetch` — Krypto-Perps gegen die HL-Meta-Universes; `xyz:`-Märkte gegen die Registry. Wenn die Registry einen `xyz:`-Markt nicht kennt, wird das aktuell **nur geloggt** und der Fetch trotzdem versucht (kann dann später am `/info` scheitern).
- Journal (Scan): Schlägt ein Markt vor `run_app_cycle` fehl, wird eine **cycle**-Zeile angehängt (`scan_cycle_phase=scan_failed`, `skipped_reason=scan_failed`, Fehlertext in `notes`). Dry-Run und Execute eines Laufs teilen sich `executed_at`; die Scan-Aggregation in `utils/journal_table.py` dedupliziert zugehörige **cycle**-Zeilen pro Batch (bei Konflikt gewinnt `execute` vor `dry_run`).

---

## Was nicht committet werden soll

- `.env` (Credentials)
- `artifacts/` (Journal, Status, Logs)
- `__pycache__/`

---

## Home Assistant Add-on: Version + Commit-Format

Wenn ein Commit das Home Assistant Add-on betrifft (z. B. `ha_addons/**` oder das Add-on Image/Deployment), dann:

- **Version bump ist Pflicht**: `ha_addons/trading_agent/config.yaml` → `version: "X.Y.Z"` erhöhen (mindestens vor `git push`, besser vor jedem Commit).
- **Commit Subject Format** (für GitHub Actions Tabelle): `[X.Y.Z] - Short summary`
  - `X.Y.Z` muss zur Add-on-Version in derselben Änderung passen.

Optional kann lokal ein Hook-Set aktiviert werden (siehe `.githooks/`), um das automatisch zu erzwingen.

### Release Command (Windows / PowerShell)

Fuer einen wiederholbaren Ablauf gibt es ein Helper-Script:
`scripts/ha_addon_release.ps1`

Beispiel (Patch-Bump, Tests, Commit, Push):
`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ha_addon_release.ps1 -Summary "..." -Bump patch -Push`

Wenn Tests fehlschlagen, wird nur der Version-Bump in `ha_addons/trading_agent/config.yaml` automatisch zurueckgesetzt, damit du fixen und neu starten kannst.
