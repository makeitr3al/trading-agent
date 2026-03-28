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
- `TRADING_JOURNAL_PATH` optional fuer einen expliziten Journal-Pfad
- `RUNNER_STATUS_PATH` optional fuer einen expliziten Status-Pfad des Managed Runners
- `TRADING_AGENT_RUNTIME_CONFIG_PATH` optional fuer die UI-gesteuerte Runtime-Override-Datei

BETA ist der sichere Default fuer Entwicklung und Tests.
PROD wird nur geladen, wenn zusaetzlich `PROPR_PROD_CONFIRM=YES` gesetzt ist.

Ungueltige oder fehlende `PROPR_LEVERAGE`-Werte fallen sicher auf `x1` zurueck.
Wenn `TRADING_JOURNAL_PATH` nicht gesetzt ist, wird automatisch pro Umgebung getrennt geschrieben, also standardmaessig nach `artifacts/trading_journal_beta.jsonl` oder `artifacts/trading_journal_prod.jsonl`.
Wenn `RUNNER_STATUS_PATH` nicht gesetzt ist, schreibt der Managed Runner standardmaessig nach `artifacts/runner_status_beta.json` oder `artifacts/runner_status_prod.json`.
Wenn `TRADING_AGENT_RUNTIME_CONFIG_PATH` nicht gesetzt ist, werden UI-Overrides standardmaessig in `artifacts/runtime_overrides.json` gespeichert.

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
- `limit` verhaelt sich wie eine echte Limit-Order: ein marketable Buy-Limit oberhalb des Marktes wird direkt zum besseren verfuegbaren Preis ausgefuehrt und nicht wie ein Stop behandelt
- `BUY_STOP` und `SELL_STOP` sind eigene Conditional-Typen und funktionieren in Beta nicht als standalone Entry; sie werden mit `requires position or group` bzw. `conditional_order_requires_position_or_group` abgelehnt
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

Das Skript prueft zuerst den Core-Health-Status, laedt die aktive Challenge, synchronisiert den externen State, rechnet den internen Agent-Zyklus und gibt das Ergebnis strukturiert aus. Vor echter Execution wird zusaetzlich geprueft, ob das Basis-Asset bei Propr ueber die Margin-Config tradebar ist und ob die konfigurierte `PROPR_LEVERAGE` das effektive Propr-Limit nicht ueberschreitet. Im Golden-Modus wird statt des Live-Marktdatenpfads genau ein bestehendes Golden-Szenario geladen und fachlich lesbar ausgegeben. Echter Submit ist dort hart blockiert. In Beta werden standalone Trend-Stop-Entries (`BUY_STOP` / `SELL_STOP`) aktuell nicht submitted, sondern sauber als bekannte Plattform-Limitation erkannt und nur gejournalt.

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

Der Multi-Market-Scanner startet mehrere Maerkte nacheinander ueber denselben App-Cycle und kann im Live-Modus auch echte Beta-Execution ausloesen.

Startbefehl:
`.\.venv\Scripts\python.exe scripts/multi_market_scan.py`

Wichtige Variablen:
- `SCAN_CONFIRM=YES`
- `SCAN_MARKETS=BTC/USDC:BTC,ETH/USDC:ETH,SOL/USDC:SOL`
- optional weiterhin `SCAN_SYMBOLS=...` plus `SCAN_HYPERLIQUID_COINS=...` als Legacy-Alternative
- `SCAN_ALLOW_SUBMIT=NO|YES`
- `DATA_SOURCE=live|golden`

Wichtig dabei:
- `SCAN_MARKETS` ist das kanonische Format und verwendet `SYMBOL:COIN`-Paare
- `SCAN_SYMBOLS` und `SCAN_HYPERLIQUID_COINS` bleiben nur als Legacy-Fallback erhalten
- echter Submit ist nur im Live-Modus moeglich; im Golden-Modus bleibt er hart blockiert
- der Scanner beruecksichtigt kontoweit maximal 3 offene Entry-Orders oder Positionen
- wenn mehr ausfuehrbare Markt-Kandidaten vorhanden sind als freie Slots, priorisiert der Scanner nach `signal_strength`; wenn genug Slots frei sind, werden alle validen Markt-Kandidaten verwendet
- `PROPR_SYMBOL` gilt nur fuer Single-Market-Skripte, nicht fuer die Markt-Auswahl des Multi-Market-Scans
- Beta-Einschraenkungen fuer standalone Stop-Entries gelten auch im Multi-Market-Scan

## Trading Journal

Jeder App-Cycle kann fortlaufend in ein JSONL-Journal schreiben. Das Journal enthaelt pro Cycle mindestens:
- Datum und Timestamp des Eintrags
- Umgebung (`beta` oder `prod`)
- empfangene Signale
- verwendete Signale
- nicht verwendete Signale inklusive Grund

Zusaetzlich werden pro vorbereiteter Order oder pro gefuelltem bzw. geschlossenen Trade eigene Eintraege geschrieben, unter anderem mit:
- Symbol
- Richtung
- Fill-Zeitpunkt, sofern vorhanden
- Position-Size
- PnL nach Close, sofern vorhanden

Standardmaessig wird pro Umgebung getrennt geschrieben:
- `artifacts/trading_journal_beta.jsonl`
- `artifacts/trading_journal_prod.jsonl`

Mit `TRADING_JOURNAL_PATH` kannst du den Zielpfad bei Bedarf explizit ueberschreiben.

## Raspberry Pi / Greenbox Betrieb

Fuer einen dauerhaften 24/7-Betrieb auf einer Greenbox oder einem Raspberry Pi ist der neue Managed Runner gedacht:
`python managed_runner.py`

Der Managed Runner verwendet intern denselben App-Cycle wie der bestehende Scheduled Runner, schreibt aber zusaetzlich einen Laufzeit-Status nach JSON. Das ist besonders praktisch fuer Monitoring, Watchdogs und Home Assistant.

Standardpfade:
- Journal: `artifacts/trading_journal_beta.jsonl` oder `artifacts/trading_journal_prod.jsonl`
- Runner-Status: `artifacts/runner_status_beta.json` oder `artifacts/runner_status_prod.json`

Wichtige Hinweise fuer den Pi:
- am besten 64-bit Linux verwenden
- den Bot als `systemd`-Service laufen lassen, nicht in einer offenen SSH-Session
- moeglichst SSD statt SD-Karte verwenden, weil Journal und Status regelmaessig geschrieben werden
- zuerst mit `PROPR_ENV=beta` und `RUNNER_ALLOW_SUBMIT=NO` ein paar Tage stabil beobachten

Im Repo liegen dafuer Beispiel-Dateien:
- `managed_runner.py`
- `run_managed_runner.sh`
- `runtime_config.py`
- `trading-agent.service.example`
- `trading-agent-sudoers.example`
- `trading-agent-tests@.service.example`

Ein typischer Linux-Ablauf ist:
1. Repo nach `/opt/trading-agent` kopieren
2. virtuelle Umgebung auf dem Pi anlegen und Dependencies installieren
3. `.env` sauber setzen
4. `trading-agent.service.example` nach `/etc/systemd/system/trading-agent.service` uebernehmen und Benutzer/Pfade anpassen
5. `sudo systemctl daemon-reload`
6. `sudo systemctl enable --now trading-agent.service`

Nuetzliche Befehle auf dem Pi:
- `systemctl status trading-agent.service`
- `journalctl -u trading-agent.service -f`
- `cat artifacts/runner_status_beta.json`

## Journal Snapshot

Fuer Monitoring und Home Assistant gibt es zusaetzlich einen kompakten Journal-Snapshot:
`python journal_snapshot.py --limit 20 --pretty`

Das Skript liest das JSONL-Journal und gibt eine kompakte JSON-Zusammenfassung aus, unter anderem mit:
- letztem Cycle-Decision-Action
- letztem Order-Status
- letztem Trade-Status und PnL
- Gesamtanzahl von Cycle-, Order- und Trade-Eintraegen
- den letzten kompakten Journal-Eintraegen

## Home Assistant Integration

Ja, das laesst sich gut integrieren. Der einfachste und robusteste Weg ist meist:
- Home Assistant fragt per SSH den Runner-Status als JSON ab
- Home Assistant fragt per SSH den Journal-Snapshot ab
- ein `shell_command` in Home Assistant fuehrt `sudo systemctl restart trading-agent.service` auf dem Pi aus

Im Repo liegt dafuer eine Beispielkonfiguration:
- `home_assistant_package.yaml.example`

Damit bekommst du typischerweise:
- Binary Sensor fuer den `systemd`-Service-Status
- Sensor fuer den aktuellen Runner-State inklusive letzter Fehler und letzter Cycle-Ausfuehrung
- Sensor fuer die aktuell effektive Runtime-Konfiguration
- Sensor fuer den letzten Testsuite-Status inklusive Return-Code und Log-Tail
- Sensor fuer die letzte Journal-Zusammenfassung
- Start-, Stop- und Restart-Commands aus Home Assistant heraus
- einen Command zum Uebernehmen von `PROPR_ENV`, `PROPR_SYMBOL`, `PROPR_LEVERAGE` und `SCAN_MARKETS`
- einen Command zum Starten einer sicheren lokalen Testsuite

Fuer Home Assistant OS ist der SSH-Weg meist am unkompliziertesten, weil der Bot auf dem Pi bleibt und Home Assistant nur beobachtet und steuert.
Fuer laengere Testlaeufe ist ein separater `systemd`-Testservice sinnvoll, weil `shell_command` in Home Assistant laut offizieller Doku nach 60 Sekunden hart beendet wird.

## UI-Gesteuerte Runtime-Konfiguration

Die wichtigsten Operator-Werte koennen jetzt ueber eine Runtime-Override-Datei gesetzt werden, ohne `.env` direkt anzufassen:
- `PROPR_ENV`
- `PROPR_SYMBOL`
- `PROPR_LEVERAGE`
- `SCAN_MARKETS`

Verwaltet wird das ueber:
`python runtime_config.py show`
`python runtime_config.py set --propr-env beta --propr-symbol BTC/USDC --propr-leverage 2 --scan-markets BTC/USDC:BTC,ETH/USDC:ETH`
`python runtime_config.py clear --all`

Die Datei liegt standardmaessig unter:
- `artifacts/runtime_overrides.json`

Wichtig dabei:
- Runtime-Overrides haben Vorrang vor den Werten aus `.env`
- ein Service-Restart ist sinnvoll, damit der laufende Bot die neuen Werte sicher uebernimmt
- `PROPR_ENV=prod` funktioniert nur, wenn in `.env` weiterhin auch `PROPR_PROD_API_KEY` und `PROPR_PROD_CONFIRM=YES` korrekt gesetzt sind
- `SCAN_MARKETS` verwendet weiterhin das kanonische Format `SYMBOL:COIN,SYMBOL:COIN`

Empfohlene HA-UI-Helper:
- `input_select` fuer `PROPR_ENV` mit `beta` und `prod`
- `input_select` fuer `PROPR_SYMBOL` mit deinen Standardmaerkten
- `input_number` fuer `PROPR_LEVERAGE`
- `input_text` fuer `SCAN_MARKETS`

Empfohlener HA-UI-Script-Ablauf:
1. `shell_command.trading_agent_apply_config` mit den aktuellen Helper-Werten aufrufen
2. `shell_command.trading_agent_restart` ausfuehren
3. den Sensor `Trading Agent Config` pruefen

## Testsuite Fuer Home Assistant

Wenn du von Home Assistant aus Tests anstossen willst, gibt es dafuer jetzt:
`python run_test_suite.py --suite preflight`

Kurze Beispielaufrufe:
- `python run_test_suite.py --suite core`
- `python run_test_suite.py --suite preflight --pytest-arg=-q`
- `python run_test_suite.py --suite unit --pytest-arg=-q`
- `python run_test_suite.py --describe-suite preflight`
- `python run_test_suite.py --suite beta_write --allow-live-beta-writes`

Verfuegbare Suites:
- `core`: fokussierte Suite fuer die zentralen Bot-, Journal- und Runtime-Pfade
- `unit`: gesamte lokale `tests/`-Suite
- `preflight`: gesamte lokale `tests/`-Suite plus `run_all_golden_scenarios.py` plus read-only `propr_smoke_test.py`
- `beta_write`: echter Beta-Write-Check mit `propr_submit_cancel_test.py` und `propr_order_types_test.py`

Das Skript schreibt zusaetzlich:
- `artifacts/test_suite_status.json`
- `artifacts/test_suite_last.log`

Damit kann Home Assistant nicht nur den Test starten, sondern auch den letzten Status, Return-Code und die letzten Log-Zeilen anzeigen.

Empfehlung fuer den Pi-Betrieb:
- in Home Assistant standardmaessig `--suite preflight` verwenden
- `beta_write` nur manuell und bewusst ausfuehren, weil dabei echte Beta-Testorders submitted und wieder gecancelt werden
- `unit` eher manuell oder nachts laufen lassen, falls die komplette Suite spuerbar laenger dauert

Damit `start`, `stop`, `restart` und `run_tests` per SSH funktionieren, braucht der Pi-Benutzer in der Praxis meist eine enge `sudoers`-Regel, zum Beispiel nur fuer:
- `/bin/systemctl start trading-agent.service`
- `/bin/systemctl stop trading-agent.service`
- `/bin/systemctl restart trading-agent.service`

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
- verwendet pro Kandidat ein Analysefenster mit Warmup-Historie vor dem eigentlichen Triggerfenster
- sucht pro Golden-Szenario bis zu 2 echte Marktbeispiele fuer die manuelle Review
- exportiert die Review-Daten zusaetzlich als JSON und als flache CSV-Tabelle mit getrennten Zeit-, Actual-, Expected-, Analysefenster- und Match-Spalten
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















## Current HAOS Operating Model

Fuer Home Assistant OS ist das aktuell empfohlene Zielbild jetzt bewusst einfacher:
- ein Git-Repo `trading-agent`
- ein Home-Assistant-Add-on `trading_agent`
- Home Assistant uebernimmt UI und Scheduling
- das Add-on fuehrt immer genau einen Lauf aus und beendet sich danach wieder
- persistente Betriebsdaten liegen getrennt unter `/share/trading-agent-data`

Die fachliche Operator-Konfiguration liegt in genau einer JSON-Datei:
- `/share/trading-agent-data/operator_config.json`

Verwaltet wird sie ueber:
- `python operator_config.py show`
- `python operator_config.py set --mode scharf --environment beta --leverage 2 --markets BTC/USDC:BTC,ETH/USDC:ETH --scheduling-enabled true --schedule-time 07:00`
- `python operator_config.py reset`

Die wichtigsten UI-Felder in Home Assistant sind:
- `Modus`: `Scharf`, `Preflight-Test`, `Beta-Write-Test`
- `Umgebung`: `beta`, `prod`
- `Leverage`
- `Maerkte` als Textfeld im Format `SYMBOL:COIN,SYMBOL:COIN`
- `Scheduling aktiv`
- `Ausfuehrungszeit`

Fuer HAOS sind die aktuellen Referenzdateien im Repo:
- `ha_addons/trading_agent/config.yaml`
- `ha_addons/trading_agent/run.sh`
- `home_assistant_package_haos_addon.yaml.example`
- `home_assistant_dashboard_haos_addon.yaml.example`
- `operator_config.py`

Der fruehere Pfad mit separatem Zusatz-Add-on fuer Tests ist nicht mehr das bevorzugte Modell.
