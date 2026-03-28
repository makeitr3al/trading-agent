# Trading Agent

Dies ist ein regelbasierter Trading Agent in Python mit:
- Bollinger Bands
- MACD-Regime
- Trend- und Gegentrend-Signalen
- Order- und Trade-Management

V1 startet ohne Broker-Anbindung.

## Signal Rules

Die Strategy verwendet drei Regime auf Basis des MACD:
- `bullish`
- `bearish`
- `neutral`

Trend-Signale:
- Trend-Signale sind nur in `bullish` oder `bearish` moeglich.
- Sie muessen innerhalb der konfigurierten maximalen Regime-Alter-Grenze liegen.
- Der Schlusskurs muss tief genug innerhalb der relevanten Bollinger-Haelfte liegen.

Gegentrend-Signale:
- Gegentrend-Signale sind in allen Regimen moeglich, also auch in `neutral`.
- In `bullish` und `bearish` bleibt die First-Bar-Regel aktiv: ein Gegentrend ist dort nur auf dem ersten Bar des Regimes valide.
- In `neutral` gibt es keine First-Bar-Regel. Die Richtung wird dann direkt aus dem Outside-Fall abgeleitet:
- oberhalb des oberen Bands => `COUNTERTREND_SHORT`
- unterhalb des unteren Bands => `COUNTERTREND_LONG`
- Pro Regime und Richtung darf es nur ein valides Gegentrend-Signal geben.

Der Pine-Verifier in [artifacts/tradingview_strategy_indicator.pine](artifacts/tradingview_strategy_indicator.pine) bildet diese Regeln fuer die visuelle Verifikation im Chart nach.

## Environment Setup

Erstelle zuerst eine lokale .env auf Basis von .env.example. Verwende dabei nur noch die kanonischen Variablennamen aus der Beispiel-Datei.

Das bevorzugte vereinfachte Schema ist jetzt:
- `PROPR_ENV=beta|prod`
- `PROPR_BETA_*` fuer Entwicklung und Tests
- `PROPR_PROD_*` fuer bewusste PROD-Nutzung
- `PROPR_SYMBOL` als gemeinsamer Default fuer manuelle Scripts und Runner
- `PROPR_REQUIRE_HEALTHY_CORE=YES|NO` fuer den Core-Health-Guard
- `PROPR_LEVERAGE` fuer die gewuenschte Leverage vor Execution
- `DATA_SOURCE=live|golden` fuer die Candle-Datenquelle
- `GOLDEN_SCENARIO` nur dann, wenn `DATA_SOURCE=golden`
- `HYPERLIQUID_*` fuer echte historische Candle-Daten

BETA ist der sichere Default fuer Entwicklung und Tests.
PROD wird nur geladen, wenn zusaetzlich `PROPR_PROD_CONFIRM=YES` gesetzt ist.

Ungueltige oder fehlende `PROPR_LEVERAGE`-Werte fallen sicher auf `x1` zurueck.

## Data Source Modes

Es gibt jetzt zwei klar getrennte Datenquellen:
- `DATA_SOURCE=live`: laedt echte historische Candles ueber Hyperliquid REST
- `DATA_SOURCE=golden`: laedt genau ein Golden-Szenario aus den bestehenden Strategy-Golden-Tests

Wenn `DATA_SOURCE=golden` gesetzt ist, muss `GOLDEN_SCENARIO` explizit angegeben werden.
Golden-Szenarien sind nur fuer fachliche Validierung gedacht. Im Golden-Modus ist echter Submit hart gesperrt.

Ein einzelnes Golden-Szenario kann zum Beispiel so gefahren werden:
- `DATA_SOURCE=golden`
- `GOLDEN_SCENARIO=valid trend long`

Wichtig: `GOLDEN_SCENARIO` verwendet den exakten Szenario-Namen aus den Golden Fixtures. Diese Namen koennen Leerzeichen enthalten.

## Hyperliquid Historical Data

Echte Marktdaten kommen jetzt von Hyperliquid Historical ueber den `/info`-Endpoint mit `candleSnapshot`.
Propr bleibt fuer Execution, Challenge-Handling und State-Sync zustaendig.

Wichtige Variablen:
- `HYPERLIQUID_COIN` ist ein Perp-Coin wie `BTC` oder `ETH`
- `PROPR_SYMBOL` bleibt separat fuer Execution- und UI-Kontext, zum Beispiel `BTC/USDC`
- `DATA_SOURCE=live` nutzt Hyperliquid Historical
- spaeter kann WebSocket fuer Live-Updates ergaenzt werden

## Propr Beta Smoke Test

Den read-only Smoke Test startest du mit:
`.\.venv\Scripts\python.exe scripts/propr_smoke_test.py`

Der Smoke Test verwendet nur lesende Endpunkte und laeuft standardmaessig gegen die Propr Beta Umgebung. PROD wird nur geladen, wenn die explizite Confirm-Variable gesetzt ist.

## Propr Beta Write Test

Der manuelle Write-Test ist nur fuer die BETA-Umgebung gedacht.

Vor dem Start:
- `PROPR_ENV=beta`
- `MANUAL_WRITE_CONFIRM=YES`
- optional `PROPR_SYMBOL=BTC/USDC`

Startbefehl:
`.\.venv\Scripts\python.exe scripts/propr_submit_cancel_test.py`

Das Skript prueft zuerst den Core-Health-Status, laedt danach die aktive Challenge, baut eine minimale Pending Order mit Decimal-Werten, loggt die verwendete `intentId` und fuehrt genau einen Submit plus direkt anschliessenden Cancel aus. Es fuehrt keinen PROD-Write aus und blockiert, wenn `MANUAL_WRITE_CONFIRM` nicht explizit auf `YES` gesetzt ist.

## Propr Beta Order Types Test

Wenn du die unterschiedlichen Order-Typen in der Beta-Umgebung manuell pruefen willst, starte:
`.\.venv\Scripts\python.exe scripts/propr_order_types_test.py`

Das Skript:
- prueft zuerst den Core-Health-Status
- laedt die aktive Challenge
- holt einen Referenzpreis ueber Hyperliquid Historical
- testet `BUY_LIMIT` und `SELL_LIMIT` als frei stehende Pending-Orders
- behandelt `BUY_STOP` und `SELL_STOP` aktuell als bekannte Beta-Einschraenkung fuer standalone conditional entries
- oeffnet danach zusaetzlich testweise eine kleine Market-Long-Position
- erstellt dafuer eine `take_profit_limit`-Exit-Order und eine `stop_market`-Exit-Order
- schliesst den offenen Trade anschliessend wieder per Market-Close
- fuehrt fuer verbleibende Exit-Orders direkt ein Cleanup per Cancel aus

Wichtig dabei:
- nur fuer `PROPR_ENV=beta`
- `MANUAL_ORDER_TYPES_CONFIRM=YES` muss gesetzt sein
- das Skript ist nur fuer manuelle Beta-Verifikation gedacht
- es fuehrt bewusst Cleanup fuer offene Test-Orders und Test-Positionen aus

Aktuell bestaetigtes Beta-Verhalten:
- dokumentiert wird `asset=BTC/USDC`, die Beta-Sandbox benoetigt fuer erfolgreiche Orders derzeit aber weiterhin einen Fallback auf `asset=BTC`
- `BUY_STOP` und `SELL_STOP` funktionieren in Beta nicht als standalone Entry und werden mit `requires position or group` abgelehnt
- `take_profit_limit` und `stop_market` funktionieren fuer bestehende Positionen, wenn `positionId` mitgegeben wird
- nach einem erfolgreichen Market-Close loest das Backend zugehoerige Exit-Orders teilweise direkt selbst auf; spaetere Cancel-Versuche koennen dann mit `order already resolved by backend lifecycle` enden
## Propr Beta Live App Cycle

Der manuelle Live App Cycle ist nur fuer die BETA-Umgebung gedacht und startet standardmaessig ohne Submit.

Vor dem Start:
- `PROPR_ENV=beta`
- `MANUAL_LIVE_CYCLE_CONFIRM=YES`
- optional `PROPR_SYMBOL=BTC/USDC`
- optional `DATA_SOURCE=golden` plus `GOLDEN_SCENARIO=...`
- bei `DATA_SOURCE=live` zusaetzlich `HYPERLIQUID_COIN=BTC` oder ein anderer Perp-Coin

Fuer einen echten Submit muessen beide Flags bewusst gesetzt werden:
- `MANUAL_LIVE_CYCLE_CONFIRM=YES`
- `MANUAL_ALLOW_SUBMIT=YES`

Startbefehl:
`.\.venv\Scripts\python.exe scripts/propr_live_app_cycle.py`

Das Skript prueft zuerst den Core-Health-Status, laedt die aktive Challenge, synchronisiert den externen State, rechnet den internen Agent-Zyklus und gibt das Ergebnis strukturiert aus. Vor echter Execution wird zusaetzlich geprueft, ob das Basis-Asset bei Propr ueber die Margin-Config tradebar ist und ob die konfigurierte `PROPR_LEVERAGE` das effektive Propr-Limit nicht ueberschreitet. Im Golden-Modus wird statt des Live-Marktdatenpfads genau ein bestehendes Golden-Szenario geladen und fachlich lesbar ausgegeben. Echter Submit ist dort hart blockiert.

## Scheduled Runner

Der generische Scheduled Runner startet manuell und verwendet eine konfigurierbare Datenquelle.

Startbefehl:
`.\.venv\Scripts\python.exe scripts/scheduled_runner.py`

Wichtige Runner-Variablen:
- `RUNNER_CONFIRM=YES` aktiviert den echten Lauf
- `RUNNER_ALLOW_SUBMIT=YES` erlaubt echte Submit-/Replace-Execution
- `RUNNER_MODE=daily|interval|manual`
- `RUNNER_TIME_UTC=07:00` fuer den Daily-Run in UTC
- `RUNNER_INTERVAL_SECONDS=60` fuer den Interval-Modus
- `DATA_SOURCE=live|golden`
- `GOLDEN_SCENARIO=...` nur fuer Golden-Modus
- `HYPERLIQUID_COIN=BTC` oder ein anderer Perp-Coin fuer Live-Daten

Im `daily`-Modus arbeitet der Runner in UTC und fuehrt pro UTC-Kalendertag hoechstens einen Run aus, sobald die konfigurierte Zeit erreicht ist.
Im `interval`-Modus fuehrt der Runner regelmaessig nach dem konfigurierten Sekundenintervall aus.
Im `manual`-Modus fuehrt der Runner genau einen Zyklus sofort aus und beendet sich danach sauber. Das ist besonders praktisch fuer Golden-Szenarien, gezielte Dry-Runs und manuelle Verifikation.
Im Live-Modus verwendet der Runner echte historische Hyperliquid-Candles.
Im Golden-Modus wird genau ein Golden-Szenario fachlich zur Validierung gefahren und klar als solcher Lauf gekennzeichnet. Echter Submit ist dort hart gesperrt, auch wenn `RUNNER_ALLOW_SUBMIT=YES` gesetzt waere.
Vor echter Execution wird zusaetzlich geprueft, ob das Asset tradebar ist und ob die konfigurierte Leverage innerhalb der effektiven Propr-Limits liegt.

Beispiel fuer einen manuellen Golden-Lauf:
- `DATA_SOURCE=golden`
- `GOLDEN_SCENARIO=valid trend long`
- `RUNNER_MODE=manual`
- `RUNNER_ALLOW_SUBMIT=NO`

## Multi-Market Scan

Der Multi-Market-Scanner startet mehrere Maerkte nacheinander als Dry-Run ueber denselben App-Cycle.

Startbefehl:
`.\.venv\Scripts\python.exe scripts/multi_market_scan.py`

Wichtige Variablen:
- `SCAN_CONFIRM=YES`
- `SCAN_SYMBOLS=BTC/USDC,ETH/USDC,SOL/USDC`
- `SCAN_HYPERLIQUID_COINS=BTC,ETH,SOL`
- `SCAN_ALLOW_SUBMIT=NO`
- `DATA_SOURCE=live|golden`

Wichtig dabei:
- `SCAN_SYMBOLS` sind die Propr-/UI-Symbole
- `SCAN_HYPERLIQUID_COINS` sind die passenden Hyperliquid-Perp-Coins
- die Reihenfolge beider Listen muss exakt zusammenpassen
- in diesem Schritt ist der Scanner immer ein Dry-Run
- Multi-market submit ist noch nicht aktiv, auch wenn `SCAN_ALLOW_SUBMIT=YES` gesetzt wird
- im Golden-Modus wird weiterhin nur fachlich validiert und kein echter Submit zugelassen

## Golden Schema Compare

Der Schema-Compare vergleicht echte Hyperliquid-Candles strukturell mit genau einem Golden-Szenario.

Startbefehl:
`.\.venv\Scripts\python.exe scripts/golden_schema_compare.py`

Wichtig dabei:
- `GOLDEN_SCENARIO` muss gesetzt sein
- das Skript laedt echte Hyperliquid-Candles ueber den bestehenden Historical Provider
- es vergleicht Shape, Reihenfolge, Zeitabstaende, Wertebereiche und Candle-Sanity
- es fuehrt keine Trades und keine Submit-Logik aus

## Historical Reference Case Scan

Wenn du fuer alle Golden-Szenarien echte historische Referenzfaelle aus Hyperliquid suchen willst, starte:
`.\.venv\Scripts\python.exe scripts/find_historical_reference_cases.py`

Das Skript:
- laedt echte historische Hyperliquid-Candles ueber den bestehenden Historical Provider
- replayt rollierende Marktfenster durch die echte Strategy-/Agent-Pipeline
- sucht pro Golden-Szenario bis zu 2 echte Marktbeispiele fuer die manuelle Review
- exportiert die Review-Daten zusaetzlich als JSON und als flache CSV-Tabelle mit getrennten Zeit-, Actual-, Expected- und Match-Spalten
- fuehrt keine Trades und keine Submit-Logik aus

## Run All Golden Scenarios

Wenn du alle Golden-Szenarien in einem Dry-Run nacheinander fachlich pruefen willst, starte:
`.\.venv\Scripts\python.exe scripts/run_all_golden_scenarios.py`

Das Skript fuehrt alle bekannten Golden-Szenarien nacheinander aus, bewertet die erwarteten Outcomes und gibt eine kompakte PASS/FAIL-Zusammenfassung aus.
Es ist bewusst nur ein Dry-Run und fuehrt keine Trades und keine Submit-Logik aus.

## Broker Notes

Die Propr-Broker-Schicht nutzt `Decimal` fuer mengen- und preisbezogene Werte und serialisiert diese als Strings fuer die API.
Jede neue Order bekommt eine eigene ULID als `intentId`.
Sowohl `200` als auch `201` gelten fuer Create/Cancel als Erfolg.
Positionen mit `quantity == 0` werden im State-Sync nicht als aktive Trades uebernommen.
Symbolgerechte Quantity-Rundung ist aktiv und wird auf Basis von `quantity_decimals` angewendet.
Preisrundung wird nur dann angewendet, wenn belastbare Preis-Praezisionsdaten als `price_decimals` verfuegbar sind. Ohne solche Daten bleibt der Preiswert unveraendert.
Echter Live-Submit wird blockiert, wenn keine SymbolSpec geladen werden kann. Dry-Runs duerfen mit Fallback weiterlaufen.
Vor einem Trading-Start sollte zusaetzlich `/health/services` geprueft werden, insbesondere der `core`-Status.
Vor echter Execution sollte das Asset ueber `/accounts/{accountId}/margin-config/{asset}` als tradebar bestaetigt werden.
Die effektiven Leverage-Limits kommen aus `/leverage-limits/effective`.
Ein erster WebSocket-Client ist fuer Live-Updates vorbereitet.
Relevante Echtzeit-Events sind aktuell:
- `order.filled`
- `position.updated`
- `trade.created`














