# Trading Agent Add-on

## Zielbild

Dieses Add-on ist der einzige Runtime-Wrapper fuer den Trading Agent auf Home Assistant OS.
Home Assistant uebernimmt UI und Scheduling, das Add-on fuehrt immer genau einen Lauf aus und beendet sich danach wieder.

## Architektur

- GitHub-Repo als Home-Assistant-Add-on-Repository
- ein einziges Add-on `trading_agent`
- persistente Betriebsdaten unter `/share/trading-agent-data`
- kein separater Code-Checkout unter `/share/trading-agent`

## Persistente Daten

Das Add-on liest und schreibt unter:
- `/share/trading-agent-data/operator_config.json`
- `/share/trading-agent-data/trading_journal_beta.jsonl`
- `/share/trading-agent-data/trading_journal_prod.jsonl`
- `/share/trading-agent-data/journal_snapshot.json`
- `/share/trading-agent-data/test_suite_status.json`
- `/share/trading-agent-data/test_suite_last.log`

## Operator-Konfiguration

Die Home-Assistant-Oberflaeche schreibt genau eine fachliche Datei:
- `/share/trading-agent-data/operator_config.json`

Die Werte darin sind:
- `mode`: `scharf`, `preflight`, `beta_write`
- `environment`: `beta`, `prod`
- `leverage`
- `markets`
- `scheduling_enabled`
- `schedule_time`

## Laufmodi

- `scharf`
  Ein echter Multi-Market-Lauf mit Submit gegen die gewaehlte Umgebung.
- `preflight`
  Fuehrt die sichere Vorab-Pruefung aus.
- `beta_write`
  Fuehrt die schreibenden Beta-Tests aus.

## Was im Add-on bleibt

Im Add-on-UI bleiben nur technische bzw. sensible Werte:
- `data_path`
- API-Keys
- `propr_prod_confirm`
- technische Hyperliquid-Defaults

## Was in Home Assistant gehoert

Die taegliche Bedienung passiert ueber Helpers, Scripts und Automationen in HA:
- Dropdown fuer `Scharf` / `Preflight-Test` / `Beta-Write-Test`
- Dropdown fuer `beta` / `prod`
- Leverage als Number
- Maerkte als Textfeld
- `Scheduling aktiv` als Boolean
- Zeithelper fuer den Tageslauf
- Textfeld fuer den Add-on-Slug
- Button `Jetzt ausfuehren`

## Scheduling

Das Add-on schedult nichts selbst.
Home Assistant startet das Add-on zur gewuenschten Zeit per Automation. Laut offizieller HA-Doku kann ein Time-Trigger direkt mit einem `input_datetime`-Helper arbeiten.
Quelle: https://www.home-assistant.io/docs/automation/trigger/