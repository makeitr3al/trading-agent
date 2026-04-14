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
- `/share/trading-agent-data/ha_save_operator_config.py` (wird beim Add-on-Start aus dem Image nach `/share` kopiert; wird von `shell_command.trading_agent_save_operator_config_haos` genutzt)

## Add-on-Upgrade / HA-Paket (Checkliste)

Nach einem **neuen Add-on-Image** oder wenn Helper (z. B. Maerkte) ploetzlich wieder **YAML-`initial:`**-Werte zeigen:

1. Pruefen, ob `/share/trading-agent-data/operator_config.json` noch existiert und sinnvolle Werte hat (Maerkte, `challenge_attempt_id`, Modus).
2. **Home-Assistant-Paket/Scripts** aus dem Repo mit deiner `/config`-Installation abgleichen (insbesondere `home_assistant_package_haos_addon.yaml.example` und `home_assistant_scripts_haos_addon.yaml.example`): neue `shell_command`-Eintraege oder Script-Sequenzen werden sonst nicht uebernommen.
3. Einmal **„Trading Agent Konfiguration laden“** (`script.trading_agent_load_current_config_haos`) ausfuehren oder HA neu starten, damit die Helper aus der Datei bzw. dem Sensor wieder befuellt werden.
4. `challenge_attempt_id` gehoert in `operator_config.json` (und im Helper **Trading Agent Challenge Attempt ID**). Ueberfluessige Anfuehrungszeichen aus Copy-Paste werden beim Laden normalisiert; trotzdem moeglichst den **Attempt**-Wert setzen, nicht nur die Challenge-URN, wenn mehrere aktive Attempts existieren.
5. Home Assistant **2024.8+** empfohlen: das Load-Script nutzt bei weiterhin `unknown`/`unavailable` vom `sensor.trading_agent_operator_config` einen **Fallback** (`shell_command.trading_agent_cat_operator_config_haos`), damit die Helper nicht auf den Default-Maerkten haengen bleiben.

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
- `challenge_attempt_id` (optional, leer fuer automatische Challenge; **empfohlen** fuer eindeutige Auswahl bei mehreren aktiven Attempts)
- `challenge_id` (legacy/optional; bleibt fuer Rueckwaertskompatibilitaet bestehen)
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

## HA Helper Sync (Scripts + Automation)

Wichtig bei YAML-definierten Helpers: Beim HA-Start koennen `input_*` Entities kurzzeitig auf ihren `initial:` Default-Werten stehen, bevor die Operator-Konfiguration geladen ist.

Die Referenzdateien stellen deshalb sicher, dass die Helpers **deterministisch** aus `sensor.trading_agent_operator_config` (Quelle: `/share/trading-agent-data/operator_config.json`) wiederhergestellt werden:

- `script.trading_agent_load_current_config_haos` wartet beim Laden bis zu **2 Minuten** darauf, dass `sensor.trading_agent_operator_config` nicht mehr `unknown`/`unavailable` ist. Erst dann werden Helper-Werte gesetzt.
- Die Automation **Trading Agent Helper Sync** triggert bei Home-Assistant-Start und zusaetzlich, wenn `sensor.trading_agent_operator_config` von `unknown`/`unavailable` auf einen gueltigen Zustand wechselt (mit kurzem Delay), damit der Restore auch bei langsamem Start nicht ausfaellt.

## HAOS Admin Panel (Sidebar)

Das Add-on liefert ein zentrales Admin-Panel fuer die komplette Bedienung aus:
- Panel-Asset: `/local/trading-agent/admin-panel.js`
- Datenquellen (vom Add-on nach jedem Lauf aktualisiert):  
  - `/local/trading-agent/journal_table.json`  
  - `/local/trading-agent/live_status.json`  
  - `/local/trading-agent/asset_registry.json`  
  - `/local/trading-agent/challenges.json`

Hinweis zur **Offene Positionen** Karte (Fallback auf Live-Status): Wenn keine Journal-Position vorhanden ist, nutzt das Panel die Position-Zusammenfassung aus `live_status.json` und akzeptiert mehrere Feldvarianten zur Kompatibilitaet:
- TP: `take_profit`, `takeProfit`, `tp`, `internal_take_profit`
- SL: `stop_loss`, `stopLoss`, `sl`, `internal_stop_loss`
- Entry: `entry_price`, `entryPrice`, `entry`
- Size: `position_size`, `positionSize`, `size`

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