# Trading Agent

Dies ist ein regelbasierter Trading Agent in Python mit:
- Bollinger Bands
- MACD-Regime
- Trend- und Gegentrend-Signalen
- Order- und Trade-Management

V1 startet ohne Broker-Anbindung.

## Environment Setup

Erstelle zuerst eine lokale `.env` auf Basis von `.env.example`.

Das bevorzugte vereinfachte Schema ist jetzt:
- `PROPR_ENV=beta|prod`
- `PROPR_BETA_*` fuer Entwicklung und Tests
- `PROPR_PROD_*` fuer bewusste PROD-Nutzung
- `PROPR_SYMBOL` als gemeinsamer Default fuer manuelle Scripts und Runner
- `PROPR_REQUIRE_HEALTHY_CORE=YES|NO` fuer den Core-Health-Guard
- `DATA_SOURCE=live|golden` fuer die Candle-Datenquelle
- `GOLDEN_SCENARIO` nur dann, wenn `DATA_SOURCE=golden`

BETA ist der sichere Default fuer Entwicklung und Tests.
PROD wird nur geladen, wenn zusaetzlich `PROPR_PROD_CONFIRM=YES` gesetzt ist.

Alte einzelne Variablennamen wie `PROPR_TEST_SYMBOL`, `WRITE_TEST_CONFIRM` oder `LIVE_APP_CYCLE_*` werden voruebergehend noch als Legacy-Fallback unterstuetzt, sind aber nicht mehr das bevorzugte Schema.

## Data Source Modes

Es gibt jetzt zwei klar getrennte Datenquellen:
- `DATA_SOURCE=live`: verwendet den aktuellen Live-Stub-Provider als Platzhalter fuer eine spaetere echte Marktdatenquelle
- `DATA_SOURCE=golden`: laedt genau ein Golden-Szenario aus den bestehenden Strategy-Golden-Tests

Wenn `DATA_SOURCE=golden` gesetzt ist, muss `GOLDEN_SCENARIO` explizit angegeben werden.
Golden-Szenarien sind nur fuer fachliche Validierung gedacht. Im Golden-Modus ist echter Submit hart gesperrt.

## Propr Beta Smoke Test

Den read-only Smoke Test startest du mit:
`python scripts/propr_smoke_test.py`

Der Smoke Test verwendet nur lesende Endpunkte und laeuft standardmaessig gegen die Propr Beta Umgebung. PROD wird nur geladen, wenn die explizite Confirm-Variable gesetzt ist.

## Propr Beta Write Test

Der manuelle Write-Test ist nur fuer die BETA-Umgebung gedacht.

Vor dem Start:
- `PROPR_ENV=beta`
- `MANUAL_WRITE_CONFIRM=YES`
- optional `PROPR_SYMBOL=BTC/USDC`

Startbefehl:
`python scripts/propr_submit_cancel_test.py`

Das Skript prueft zuerst den Core-Health-Status, laedt danach die aktive Challenge, baut eine minimale Pending Order mit Decimal-Werten, loggt die verwendete `intentId` und fuehrt genau einen Submit plus direkt anschliessenden Cancel aus. Es fuehrt keinen PROD-Write aus und blockiert, wenn `MANUAL_WRITE_CONFIRM` nicht explizit auf `YES` gesetzt ist.

## Propr Beta Live App Cycle

Der manuelle Live App Cycle ist nur fuer die BETA-Umgebung gedacht und startet standardmaessig ohne Submit.

Vor dem Start:
- `PROPR_ENV=beta`
- `MANUAL_LIVE_CYCLE_CONFIRM=YES`
- optional `PROPR_SYMBOL=BTC/USDC`
- optional `DATA_SOURCE=golden` plus `GOLDEN_SCENARIO=...`

Fuer einen echten Submit muessen beide Flags bewusst gesetzt werden:
- `MANUAL_LIVE_CYCLE_CONFIRM=YES`
- `MANUAL_ALLOW_SUBMIT=YES`

Startbefehl:
`python scripts/propr_live_app_cycle.py`

Das Skript prueft zuerst den Core-Health-Status, laedt die aktive Challenge, synchronisiert den externen State, rechnet den internen Agent-Zyklus und gibt das Ergebnis strukturiert aus. Im Golden-Modus wird statt des Live-Stub-Providers genau ein bestehendes Golden-Szenario geladen. Echter Submit ist dort hart blockiert.

## Scheduled Runner

Der generische Scheduled Runner startet manuell und verwendet eine konfigurierbare Datenquelle.

Startbefehl:
`python scripts/scheduled_runner.py`

Wichtige Runner-Variablen:
- `RUNNER_CONFIRM=YES` aktiviert den echten Lauf
- `RUNNER_ALLOW_SUBMIT=YES` erlaubt echte Submit-/Replace-Execution
- `RUNNER_MODE=daily|interval`
- `RUNNER_TIME_UTC=07:00` fuer den Daily-Run in UTC
- `RUNNER_INTERVAL_SECONDS=60` fuer den Interval-Modus
- `DATA_SOURCE=live|golden`
- `GOLDEN_SCENARIO=...` nur fuer Golden-Modus

Im `daily`-Modus arbeitet der Runner in UTC und fuehrt pro UTC-Kalendertag hoechstens einen Run aus, sobald die konfigurierte Zeit erreicht ist.
Im Golden-Modus ist echter Submit hart gesperrt, auch wenn `RUNNER_ALLOW_SUBMIT=YES` gesetzt waere.

## Broker Notes

Die Propr-Broker-Schicht nutzt `Decimal` fuer mengen- und preisbezogene Werte und serialisiert diese als Strings fuer die API.
Jede neue Order bekommt eine eigene ULID als `intentId`.
Sowohl `200` als auch `201` gelten fuer Create/Cancel als Erfolg.
Positionen mit `quantity == 0` werden im State-Sync nicht als aktive Trades uebernommen.
Vor einem Trading-Start sollte zusaetzlich `/health/services` geprueft werden, insbesondere der `core`-Status.
Ein erster WebSocket-Client ist fuer Live-Updates vorbereitet.
Relevante Echtzeit-Events sind aktuell:
- `order.filled`
- `position.updated`
- `trade.created`
