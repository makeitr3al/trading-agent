# Trading Agent Add-on

## Zielbild

Dieses Add-on ist der einzige Runtime-Wrapper fuer den Trading Agent auf Home Assistant OS.
Home Assistant uebernimmt UI und Scheduling, das Add-on fuehrt immer genau einen Lauf aus und beendet sich danach wieder.

## Ordnerstruktur auf HAOS

- `/share/trading-agent`
  Git-Checkout des Python-Repos
- `/share/trading-agent-data`
  Persistente Betriebsdaten fuer Operator-Konfiguration, Journal und Teststatus
- `/addons/local/trading_agent`
  Add-on-Wrapper aus `ha_addons/trading_agent`

## Operator-Konfiguration

Die Bedienoberflaeche in Home Assistant schreibt eine einzige Datei:
- `/share/trading-agent-data/operator_config.json`

Diese Datei enthaelt die fachlichen Operator-Werte:
- `mode`: `scharf`, `preflight`, `beta_write`
- `environment`: `beta`, `prod`
- `leverage`
- `markets`
- `scheduling_enabled`
- `schedule_time`

Die Datei wird ueber `operator_config.py` verwaltet, nicht ueber rohe Env-Variablen.

## Laufmodi

- `scharf`
  Ein echter Multi-Market-Lauf mit Submit gegen die gewaehlte Umgebung.
- `preflight`
  Fuehrt die sichere Vorab-Pruefung aus.
- `beta_write`
  Fuehrt die schreibenden Beta-Tests aus.

## Was im Add-on bleibt

Im Add-on-UI bleiben nur technische bzw. sensible Werte:
- `repo_path`
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
- Button `Jetzt ausfuehren`

## Scheduling

Das Add-on schedult nichts selbst.
Home Assistant startet das Add-on zur gewuenschten Zeit per Automation. Laut offizieller HA-Doku kann ein Time-Trigger direkt mit einem `input_datetime`-Helper arbeiten.
Quelle: https://www.home-assistant.io/docs/automation/trigger/

## Hinweis zu alten Zwischenloesungen

Die frueheren Runtime-Override- und Extra-Task-Layer sind fuer das aktuelle Zielbild nicht mehr der bevorzugte Weg. Die aktuelle Referenz fuer HAOS ist:
- `operator_config.py`
- `home_assistant_package_haos_addon.yaml.example`
- `home_assistant_dashboard_haos_addon.yaml.example`
