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
- `challenge_id` (optional, leer fuer automatische Challenge)
- `push_enabled` (optional, HA-Benachrichtigungen; wird vom Add-on nicht fuer Trading ausgewertet)

Das Admin-Panel (Lovelace) schreibt Aenderungen an den Operator-Helpers mit kurzer Verzoegerung (Debouncing) automatisch ueber das Script `trading_agent_save_current_config_haos` in dieselbe Datei, damit ein HA-Neustart und die Konfiguration-Sync-Automation dieselben Werte wiederherstellen.

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
- `Push aktiv` als Boolean (persistiert in `operator_config.json` als `push_enabled`)
- Zeithelper fuer den Tageslauf
- Textfeld fuer den Add-on-Slug
- Button `Jetzt ausfuehren`

## Scheduling

Das Add-on schedult nichts selbst.
Home Assistant startet das Add-on zur gewuenschten Zeit per Automation. Laut offizieller HA-Doku kann ein Time-Trigger direkt mit einem `input_datetime`-Helper arbeiten.
Quelle: https://www.home-assistant.io/docs/automation/trigger/

## HAOS Admin Panel (Sidebar)

Das Add-on liefert ein zentrales Admin-Panel fuer die komplette Bedienung aus:
- Panel-Asset: `/local/trading-agent/admin-panel.js`
- Datenquellen (vom Add-on nach jedem Lauf aktualisiert):  
  - `/local/trading-agent/journal_table.json`  
  - `/local/trading-agent/live_status.json`  
  - `/local/trading-agent/asset_registry.json`  
  - `/local/trading-agent/challenges.json`

### Viewer-Umgebung vs. Operator-Umgebung

Wichtig: Im Admin-Panel gibt es **zwei** Umgebungs-Begriffe:
- **Operator-Umgebung** (`environment` in `operator_config.json`): steuert, gegen welche Propr-Umgebung der *naechste* Add-on-Lauf arbeitet.
- **Viewer-Umgebung** (Dropdown „Viewer Umgebung“ im Panel): steuert nur, welche env-spezifischen JSON-Ansichten das Panel gerade laedt.

Damit die Viewer-Umschaltung ohne Datenmix funktioniert, schreibt das Add-on zusaetzlich env-spezifische Dateien nach `/config/www/trading-agent`:
- `journal_table_beta.json` und `journal_table_prod.json`
- `live_status_beta.json` und `live_status_prod.json`
- `challenges_beta.json` und `challenges_prod.json`

Wenn eine env-spezifische Datei fehlt, faellt das Panel automatisch auf die Legacy-Datei ohne Suffix zurueck.

### Versionierung, Cache-Busting und HA Restart

Home Assistant cached `panel_custom` Module sehr aggressiv. Deshalb:
- Das Add-on injiziert seine Version in das Panel-Asset und schreibt zusaetzlich `panel_version.txt` unter `/local/trading-agent/`.
- Das Add-on aktualisiert bei Versionswechsel automatisch den `?v=` Cache-Buster in `/config/configuration.yaml` (nur, wenn dort bereits ein `admin-panel.js` Eintrag existiert) und triggert danach einen HA Core Restart, damit das neue Panel geladen wird.

Du musst den `?v=` Wert daher nicht manuell pflegen; die Referenzdatei `home_assistant_panel_haos_addon.yaml.example` zeigt nur ein typisches Startbeispiel.