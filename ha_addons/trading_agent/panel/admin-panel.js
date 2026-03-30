const PANEL_NAME = "trading-agent-admin-panel";
const JOURNAL_URL = "/local/trading-agent/journal_table.json";
const HOME_URL = "/lovelace";

const ENTITIES = {
  addonSlug: "input_text.trading_agent_addon_slug",
  mode: "input_select.trading_agent_mode",
  environment: "input_select.trading_agent_environment",
  leverage: "input_number.trading_agent_leverage",
  markets: "input_text.trading_agent_markets",
  scheduleEnabled: "input_boolean.trading_agent_scheduling_aktiv",
  scheduleTime: "input_datetime.trading_agent_schedule_time",
  pushEnabled: "input_boolean.trading_agent_push_aktiv",
  notifyAction: "input_text.trading_agent_notify_action",
  operatorConfig: "sensor.trading_agent_operator_config",
  runSummary: "sensor.trading_agent_run_summary",
  tests: "sensor.trading_agent_tests",
  journal: "sensor.trading_agent_journal",
};

const SCRIPT_BUTTONS = [
  ["script.trading_agent_jetzt_ausfuehren_haos", "Aktuellen Modus ausfuehren"],
  ["script.trading_agent_preflight_test_haos", "Preflight-Test"],
  ["script.trading_agent_beta_write_test_haos", "Beta-Write-Test"],
  ["script.trading_agent_scharf_lauf_haos", "Scharf-Lauf"],
  ["script.trading_agent_stop_haos", "Stopp"],
  ["script.trading_agent_neustart_haos", "Neustart"],
  ["script.trading_agent_reset_operator_config_haos", "Konfiguration zuruecksetzen"],
];

const TABS = [
  ["controls", "Steuerung"],
  ["status", "Status"],
  ["scans", "Journal Scans"],
  ["trades", "Journal Orders & Trades"],
];

const SCAN_COLUMNS = [
  { key: "timestamp", label: "Zeit", sortable: true, filter: "text" },
  { key: "symbol", label: "Markt", sortable: true, filter: "select", optionKey: "symbols" },
  { key: "environment", label: "Umgebung", sortable: true, filter: "select", optionKey: "environments" },
  { key: "decision_action", label: "Decision", sortable: true, filter: "select", optionKey: "decision_actions", badge: true },
  { key: "selected_signal_type", label: "Verwendetes Signal", sortable: true, filter: "select", optionKey: "scan_signals" },
  { key: "received_signals", label: "Empfangene Signale", filter: "text" },
  { key: "order_created", label: "Order erstellt", sortable: true, filter: "select", boolean: true },
  { key: "follow_up", label: "Order/Trade-Folge", filter: "text" },
  { key: "skip_reason", label: "Skip-Grund", filter: "text" },
  { key: "notes", label: "Notizen", filter: "text" },
];

const TRADE_COLUMNS = [
  { key: "timestamp", label: "Zeit", sortable: true, filter: "text" },
  { key: "entry_type", label: "Typ", sortable: true, filter: "select", optionKey: "entry_types", badge: true },
  { key: "symbol", label: "Markt", sortable: true, filter: "select", optionKey: "symbols" },
  { key: "environment", label: "Umgebung", sortable: true, filter: "select", optionKey: "environments" },
  { key: "status", label: "Status", sortable: true, filter: "select", optionKey: "trade_statuses", badge: true },
  { key: "direction", label: "Richtung", sortable: true, filter: "select", optionKey: "directions", badge: true },
  { key: "source_signal_type", label: "Signalquelle", sortable: true, filter: "select", optionKey: "signal_sources" },
  { key: "position_size", label: "Groesse", sortable: true, filter: "text" },
  { key: "pnl", label: "PnL", sortable: true, filter: "text" },
  { key: "fill_timestamp", label: "Fill-Zeit", sortable: true, filter: "text" },
  { key: "close_timestamp", label: "Close-Zeit", sortable: true, filter: "text" },
  { key: "notes", label: "Notizen", filter: "text" },
];

const BASE_TABLE_STATE = {
  search: "",
  filters: {},
  sortKey: "timestamp",
  sortDirection: "desc",
  page: 1,
  pageSize: 50,
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "boolean") return value ? "Ja" : "Nein";
  if (typeof value === "string" && value.includes("T")) {
    const date = new Date(value);
    if (!Number.isNaN(date.getTime())) {
      return new Intl.DateTimeFormat("de-CH", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }).format(date);
    }
  }
  return escapeHtml(value);
}

function badgeClass(value) {
  const normalized = String(value ?? "").toLowerCase();
  if (["submitted", "filled", "closed", "success", "ok", "completed", "true"].some((token) => normalized.includes(token))) {
    return "ok";
  }
  if (["failed", "error", "invalid", "not_executed"].some((token) => normalized.includes(token))) {
    return "bad";
  }
  if (["prepared", "preflight", "beta_write", "replaced", "long", "short"].some((token) => normalized.includes(token))) {
    return "info";
  }
  return "neutral";
}

function compareValues(left, right) {
  if (left === right) return 0;
  if (left === null || left === undefined || left === "") return -1;
  if (right === null || right === undefined || right === "") return 1;
  const leftNumber = Number(left);
  const rightNumber = Number(right);
  if (!Number.isNaN(leftNumber) && !Number.isNaN(rightNumber)) {
    if (leftNumber === rightNumber) return 0;
    return leftNumber < rightNumber ? -1 : 1;
  }
  return String(left).localeCompare(String(right), "de");
}

function uniqueValues(rows, key) {
  return [...new Set(rows.map((row) => row[key]).filter((value) => value !== null && value !== undefined && value !== ""))]
    .sort((left, right) => String(left).localeCompare(String(right), "de"));
}

function buildFilterOptions(scanRows, tradeRows) {
  const allRows = [...scanRows, ...tradeRows];
  return {
    symbols: uniqueValues(allRows, "symbol"),
    environments: uniqueValues(allRows, "environment"),
    decision_actions: uniqueValues(scanRows, "decision_action"),
    scan_signals: uniqueValues(scanRows, "selected_signal_type"),
    entry_types: uniqueValues(tradeRows, "entry_type"),
    trade_statuses: uniqueValues(tradeRows, "status"),
    directions: uniqueValues(tradeRows, "direction"),
    signal_sources: uniqueValues(tradeRows, "source_signal_type"),
  };
}

function cellValue(row, column) {
  if (column.key === "follow_up") {
    const orderPart = row.order_status_summary || "-";
    const tradePart = row.trade_status_summary || "-";
    const pnlPart = row.trade_pnl_summary ? ` | PnL ${row.trade_pnl_summary}` : "";
    return `${orderPart} / ${tradePart}${pnlPart}`;
  }
  return row[column.key];
}

function filterRows(rows, columns, tableState) {
  const search = (tableState.search || "").trim().toLowerCase();
  const filtered = rows.filter((row) => {
    if (search) {
      const haystack = columns.map((column) => String(cellValue(row, column) ?? "")).join(" ").toLowerCase();
      if (!haystack.includes(search)) return false;
    }
    return columns.every((column) => {
      const filterValue = (tableState.filters[column.key] || "").trim().toLowerCase();
      if (!filterValue) return true;
      const currentValue = String(cellValue(row, column) ?? "").toLowerCase();
      if (column.boolean) {
        if (filterValue === "ja") return currentValue === "true";
        if (filterValue === "nein") return currentValue === "false";
      }
      return column.filter === "select" ? currentValue === filterValue : currentValue.includes(filterValue);
    });
  });
  const sorted = [...filtered];
  const sortColumn = columns.find((column) => column.key === tableState.sortKey);
  if (sortColumn) {
    sorted.sort((left, right) => {
      const result = compareValues(cellValue(left, sortColumn), cellValue(right, sortColumn));
      return tableState.sortDirection === "asc" ? result : -result;
    });
  }
  return sorted;
}
function snapshotFallback(journalState) {
  const recentEntries = journalState?.attributes?.recent_entries || [];
  const scanRows = recentEntries
    .filter((entry) => entry.entry_type === "cycle")
    .map((entry) => ({
      timestamp: entry.entry_timestamp || null,
      entry_date: entry.entry_date || null,
      symbol: entry.symbol || null,
      environment: entry.environment || null,
      decision_action: entry.decision_action || null,
      selected_signal_type: entry.source_signal_type || null,
      received_signals: entry.source_signal_type || null,
      order_created: false,
      order_status_summary: null,
      trade_status_summary: null,
      trade_pnl_summary: entry.pnl ?? null,
      skip_reason: entry.skipped_reason || null,
      notes: entry.notes || null,
    }));
  const tradeRows = recentEntries
    .filter((entry) => entry.entry_type && entry.entry_type !== "cycle")
    .map((entry) => ({
      timestamp: entry.entry_timestamp || null,
      entry_type: entry.entry_type || null,
      symbol: entry.symbol || null,
      environment: entry.environment || null,
      status: entry.status || null,
      direction: entry.direction || null,
      source_signal_type: entry.source_signal_type || null,
      position_size: entry.position_size ?? null,
      pnl: entry.pnl ?? null,
      fill_timestamp: entry.fill_timestamp || null,
      close_timestamp: entry.close_timestamp || null,
      notes: entry.notes || null,
    }));
  if (!scanRows.length && !tradeRows.length) {
    return {
      generated_at: null,
      latest_entry_timestamp: null,
      journal_path: null,
      exists: false,
      entry_count_total: 0,
      scan_rows: [],
      trade_rows: [],
      filter_options: buildFilterOptions([], []),
      warnings: [],
    };
  }
  return {
    generated_at: journalState?.attributes?.latest_entry_timestamp || null,
    latest_entry_timestamp: journalState?.attributes?.latest_entry_timestamp || null,
    journal_path: journalState?.attributes?.journal_path || null,
    exists: Boolean(journalState?.attributes?.exists),
    entry_count_total: Number(journalState?.attributes?.entry_count || scanRows.length + tradeRows.length || 0),
    scan_rows: scanRows,
    trade_rows: tradeRows,
    filter_options: buildFilterOptions(scanRows, tradeRows),
    warnings: [
      "Panel verwendet Journal-Snapshot als Fallback, weil /local/trading-agent/journal_table.json leer oder veraltet ist.",
    ],
  };
}

class TradingAgentAdminPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.hassState = null;
    this.panelConfig = null;
    this.currentTab = "controls";
    this.journalPayload = {
      generated_at: null,
      latest_entry_timestamp: null,
      entry_count_total: 0,
      scan_rows: [],
      trade_rows: [],
      filter_options: buildFilterOptions([], []),
      warnings: [],
    };
    this.loadError = null;
    this.loading = false;
    this.lastRunId = null;
    this.tableState = {
      scans: { ...BASE_TABLE_STATE },
      trades: { ...BASE_TABLE_STATE },
    };
  }
  connectedCallback() {
    this.shadowRoot.addEventListener("click", (event) => this.onClick(event));
    this.shadowRoot.addEventListener("change", (event) => this.onChange(event));
    this.shadowRoot.addEventListener("input", (event) => this.onInput(event));
    this.refreshJournal();
    this.render();
  }

  set hass(value) {
    this.hassState = value;
    const runId = value?.states?.[ENTITIES.runSummary]?.state;
    if (runId && !["unknown", "unavailable"].includes(runId) && runId !== this.lastRunId) {
      this.lastRunId = runId;
      this.refreshJournal();
    }
    this.render();
  }

  set panel(value) {
    this.panelConfig = value;
    this.render();
  }

  entity(entityId) {
    return this.hassState?.states?.[entityId];
  }

  async callService(domain, service, data = {}) {
    if (this.hassState) {
      await this.hassState.callService(domain, service, data);
    }
  }

  async setEntityValue(entityId, value) {
    if (entityId.startsWith("input_select.")) {
      return this.callService("input_select", "select_option", { entity_id: entityId, option: value });
    }
    if (entityId.startsWith("input_number.")) {
      return this.callService("input_number", "set_value", { entity_id: entityId, value: Number(value) });
    }
    if (entityId.startsWith("input_text.")) {
      return this.callService("input_text", "set_value", { entity_id: entityId, value });
    }
    if (entityId.startsWith("input_boolean.")) {
      return this.callService("input_boolean", value ? "turn_on" : "turn_off", { entity_id: entityId });
    }
    if (entityId.startsWith("input_datetime.")) {
      return this.callService("input_datetime", "set_datetime", { entity_id: entityId, time: value });
    }
    return Promise.resolve();
  }

  async refreshJournal() {
    this.loading = true;
    this.loadError = null;
    this.render();
    try {
      const response = await fetch(`${JOURNAL_URL}?ts=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      this.journalPayload = await response.json();
    } catch (error) {
      this.loadError = error instanceof Error ? error.message : String(error);
    } finally {
      this.loading = false;
      this.render();
    }
  }

  effectiveJournal() {
    const live = this.journalPayload || {};
    if ((live.entry_count_total || 0) > 0 || (live.scan_rows?.length || 0) > 0 || (live.trade_rows?.length || 0) > 0) {
      return live;
    }
    return snapshotFallback(this.entity(ENTITIES.journal));
  }

  setTableState(name, patch) {
    this.tableState = {
      ...this.tableState,
      [name]: {
        ...this.tableState[name],
        ...patch,
      },
    };
    this.render();
  }

  field(entityId, type = "text", extra = {}) {
    const state = this.entity(entityId);
    const rawValue = state?.state ?? "";
    const value = type === "time" ? String(rawValue).slice(0, 5) : rawValue;
    const label = extra.label || state?.attributes?.friendly_name || entityId;
    if (type === "select") {
      return `<label class="field"><span>${escapeHtml(label)}</span><select data-entity="${entityId}">${(state?.attributes?.options || [])
        .map((option) => `<option value="${escapeHtml(option)}" ${option === value ? "selected" : ""}>${escapeHtml(option)}</option>`)
        .join("")}</select></label>`;
    }
    if (type === "checkbox") {
      return `<label class="toggle"><input type="checkbox" data-entity="${entityId}" ${state?.state === "on" ? "checked" : ""}><span>${escapeHtml(label)}</span></label>`;
    }
    return `<label class="field"><span>${escapeHtml(label)}</span><input data-entity="${entityId}" type="${type}" value="${escapeHtml(value)}"></label>`;
  }

  statusCard(title, rows) {
    return `<section class="card"><h3>${escapeHtml(title)}</h3><div class="status-list">${rows
      .map(
        ([label, value, useBadge]) =>
          `<div class="status-row"><span class="label">${escapeHtml(label)}</span><span class="value">${
            useBadge ? `<span class="pill ${badgeClass(value)}">${formatValue(value)}</span>` : formatValue(value)
          }</span></div>`
      )
      .join("")}</div></section>`;
  }
  controlsTab() {
    return `<div class="stack">
      <section class="card">
        <h3>Operator</h3>
        <div class="grid two">
          ${this.field(ENTITIES.mode, "select")}
          ${this.field(ENTITIES.environment, "select")}
          ${this.field(ENTITIES.leverage, "number")}
          ${this.field(ENTITIES.scheduleTime, "time")}
          ${this.field(ENTITIES.markets)}
          ${this.field(ENTITIES.addonSlug)}
        </div>
        <div class="toggle-row">${this.field(ENTITIES.scheduleEnabled, "checkbox")}</div>
      </section>
      <section class="card">
        <h3>Benachrichtigungen</h3>
        <div class="grid two">${this.field(ENTITIES.notifyAction)}</div>
        <div class="toggle-row">${this.field(ENTITIES.pushEnabled, "checkbox")}</div>
      </section>
      <section class="card">
        <h3>Aktionen</h3>
        <div class="button-grid">${SCRIPT_BUTTONS.map(([entityId, label]) => `<button class="btn" data-action="script" data-script="${entityId}">${escapeHtml(label)}</button>`).join("")}</div>
      </section>
    </div>`;
  }

  statusTab() {
    const journal = this.effectiveJournal();
    const operator = this.entity(ENTITIES.operatorConfig);
    const runSummary = this.entity(ENTITIES.runSummary);
    const tests = this.entity(ENTITIES.tests);
    const journalSensor = this.entity(ENTITIES.journal);
    const summaryLines = runSummary?.attributes?.summary_lines || [];
    return `<div class="stack">
      <div class="grid cards">
        ${this.statusCard("Operator Config", [
          ["Modus", operator?.state, true],
          ["Umgebung", operator?.attributes?.environment, true],
          ["Leverage", operator?.attributes?.leverage],
          ["Maerkte", operator?.attributes?.markets],
          ["Scheduling", operator?.attributes?.scheduling_enabled],
          ["Zeit", operator?.attributes?.schedule_time],
        ])}
        ${this.statusCard("Letzter Lauf", [
          ["Run ID", runSummary?.state],
          ["Titel", runSummary?.attributes?.title],
          ["Exit Code", runSummary?.attributes?.exit_code, true],
          ["Erfolg", runSummary?.attributes?.success, true],
          ["Suite", runSummary?.attributes?.suite],
          ["Outcome", runSummary?.attributes?.latest_outcome, true],
        ])}
        ${this.statusCard("Tests", [
          ["Runner State", tests?.state, true],
          ["Suite", tests?.attributes?.suite],
          ["Success", tests?.attributes?.success, true],
          ["Return Code", tests?.attributes?.return_code],
          ["Last Error", tests?.attributes?.last_error],
        ])}
        ${this.statusCard("Journal", [
          ["State", journalSensor?.state, true],
          ["Entry Count", journal.entry_count_total || journalSensor?.attributes?.entry_count],
          ["Cycle Count", journalSensor?.attributes?.cycle_count],
          ["Order Count", journalSensor?.attributes?.order_count],
          ["Trade Count", journalSensor?.attributes?.trade_count],
          ["Letzter Eintrag", journal.latest_entry_timestamp || journalSensor?.attributes?.latest_entry_timestamp],
        ])}
      </div>
      <section class="card">
        <div class="toolbar">
          <div>
            <h3>Laufzusammenfassung</h3>
            <p class="muted">Die gleiche Summary wird auch fuer Push-Nachrichten genutzt.</p>
          </div>
          <button class="ghost" data-action="refresh">Journal neu laden</button>
        </div>
        ${summaryLines.length ? `<ul class="summary">${summaryLines.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>` : `<p class="muted">Noch keine Zusammenfassung vorhanden.</p>`}
        ${journal.warnings?.length ? `<div class="warn">${journal.warnings.map((warning) => `<div>${escapeHtml(warning)}</div>`).join("")}</div>` : ""}
      </section>
    </div>`;
  }
  tableTab(name, columns, rows) {
    const journal = this.effectiveJournal();
    const state = this.tableState[name];
    const filteredRows = filterRows(rows, columns, state);
    const totalPages = Math.max(1, Math.ceil(filteredRows.length / state.pageSize));
    const page = Math.min(state.page, totalPages);
    const pageRows = filteredRows.slice((page - 1) * state.pageSize, (page - 1) * state.pageSize + state.pageSize);
    const options = journal.filter_options || buildFilterOptions([], []);
    return `<div class="stack">
      <section class="card">
        <div class="toolbar">
          <div>
            <h3>${escapeHtml(name === "scans" ? "Journal Scans" : "Journal Orders & Trades")}</h3>
            <p class="muted">Gesamt: ${filteredRows.length} gefilterte Zeilen von ${rows.length}. Letztes Update: ${formatValue(journal.generated_at)}</p>
          </div>
          <div class="toolbar-actions">
            <input class="search" type="search" placeholder="Globale Textsuche" data-table="${name}" data-search="1" value="${escapeHtml(state.search)}">
            <select data-table="${name}" data-pagesize="1">${[25, 50, 100, 200]
              .map((size) => `<option value="${size}" ${size === state.pageSize ? "selected" : ""}>${size} / Seite</option>`)
              .join("")}</select>
            <button class="ghost" data-action="reset" data-table="${name}">Filter zuruecksetzen</button>
            <button class="ghost" data-action="refresh">Neu laden</button>
          </div>
        </div>
        ${this.loading ? `<p class="muted">Journal wird geladen...</p>` : ""}
        ${this.loadError ? `<div class="warn">Journal konnte nicht geladen werden: ${escapeHtml(this.loadError)}</div>` : ""}
        ${journal.warnings?.length ? `<div class="warn">${journal.warnings.map((warning) => `<div>${escapeHtml(warning)}</div>`).join("")}</div>` : ""}
        <div class="table-wrap">
          <table>
            <thead>
              <tr>${columns
                .map((column) =>
                  column.sortable
                    ? `<th><button class="sort" data-action="sort" data-table="${name}" data-key="${column.key}">${escapeHtml(column.label)}${
                        state.sortKey === column.key ? ` ${state.sortDirection === "asc" ? "↑" : "↓"}` : ""
                      }</button></th>`
                    : `<th>${escapeHtml(column.label)}</th>`
                )
                .join("")}</tr>
              <tr>${columns
                .map((column) => {
                  if (!column.filter) return "<th></th>";
                  if (column.filter === "select") {
                    const choices = [...(options[column.optionKey] || [])];
                    if (column.boolean) {
                      choices.unshift("Nein");
                      choices.unshift("Ja");
                    }
                    return `<th><select data-table="${name}" data-filter="${column.key}">
                      <option value="">Alle</option>
                      ${choices
                        .map((choice) => `<option value="${escapeHtml(choice)}" ${state.filters[column.key] === choice ? "selected" : ""}>${escapeHtml(choice)}</option>`)
                        .join("")}
                    </select></th>`;
                  }
                  return `<th><input type="text" placeholder="Filter" data-table="${name}" data-filter="${column.key}" value="${escapeHtml(state.filters[column.key] || "")}"></th>`;
                })
                .join("")}</tr>
            </thead>
            <tbody>
              ${pageRows.length
                ? pageRows
                    .map(
                      (row) =>
                        `<tr>${columns
                          .map((column) => {
                            const value = cellValue(row, column);
                            if (column.key.includes("timestamp")) return `<td>${formatValue(value)}</td>`;
                            if (column.badge) return `<td><span class="pill ${badgeClass(value)}">${formatValue(value)}</span></td>`;
                            if (column.boolean) return `<td>${value ? "Ja" : "Nein"}</td>`;
                            return `<td>${formatValue(value)}</td>`;
                          })
                          .join("")}</tr>`
                    )
                    .join("")
                : `<tr><td colspan="${columns.length}" class="empty">Keine Eintraege fuer die aktuelle Ansicht gefunden.</td></tr>`}
            </tbody>
          </table>
        </div>
        <div class="pager">
          <span>Seite ${page} / ${totalPages}</span>
          <div class="pager-btns">
            <button class="ghost" data-action="page" data-table="${name}" data-page="1" ${page === 1 ? "disabled" : ""}>Erste</button>
            <button class="ghost" data-action="page" data-table="${name}" data-page="${Math.max(1, page - 1)}" ${page === 1 ? "disabled" : ""}>Zurueck</button>
            <button class="ghost" data-action="page" data-table="${name}" data-page="${Math.min(totalPages, page + 1)}" ${page === totalPages ? "disabled" : ""}>Weiter</button>
            <button class="ghost" data-action="page" data-table="${name}" data-page="${totalPages}" ${page === totalPages ? "disabled" : ""}>Letzte</button>
          </div>
        </div>
      </section>
    </div>`;
  }

  onClick(event) {
    const target = event.target.closest("[data-action]");
    if (!target) return;
    const { action, tab, script, table, key, page } = target.dataset;
    if (action === "tab" && tab) {
      this.currentTab = tab;
      this.render();
      return;
    }
    if (action === "refresh") {
      this.refreshJournal();
      return;
    }
    if (action === "home") {
      window.location.assign(HOME_URL);
      return;
    }
    if (action === "script" && script) {
      this.callService("script", "turn_on", { entity_id: script });
      return;
    }
    if (action === "sort" && table && key) {
      const current = this.tableState[table];
      this.setTableState(table, {
        sortKey: key,
        sortDirection: current.sortKey === key && current.sortDirection === "asc" ? "desc" : "asc",
        page: 1,
      });
      return;
    }
    if (action === "reset" && table) {
      this.setTableState(table, { ...BASE_TABLE_STATE });
      return;
    }
    if (action === "page" && table) {
      this.setTableState(table, { page: Number(page) });
    }
  }

  onChange(event) {
    const target = event.target;
    if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return;
    const entityId = target.dataset.entity;
    if (entityId) {
      this.setEntityValue(entityId, target instanceof HTMLInputElement && target.type === "checkbox" ? target.checked : target.value);
      return;
    }
    const { table, filter, pagesize } = target.dataset;
    if (table && filter) {
      this.setTableState(table, {
        filters: {
          ...this.tableState[table].filters,
          [filter]: target.value,
        },
        page: 1,
      });
      return;
    }
    if (table && pagesize) {
      this.setTableState(table, { pageSize: Number(target.value), page: 1 });
    }
  }

  onInput(event) {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    const { table, search } = target.dataset;
    if (table && search) {
      this.setTableState(table, { search: target.value, page: 1 });
    }
  }
  render() {
    const journal = this.effectiveJournal();
    const title = this.panelConfig?.config?.title || "Trading Agent";
    const body =
      this.currentTab === "controls"
        ? this.controlsTab()
        : this.currentTab === "status"
          ? this.statusTab()
          : this.currentTab === "scans"
            ? this.tableTab("scans", SCAN_COLUMNS, journal.scan_rows || [])
            : this.tableTab("trades", TRADE_COLUMNS, journal.trade_rows || []);

    this.shadowRoot.innerHTML = `<style>
      :host { display: block; height: 100%; background: linear-gradient(180deg, #f6f8fb 0%, #eef3f8 100%); color: #162133; font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; }
      .page { min-height: 100vh; padding: 24px; box-sizing: border-box; }
      .hero { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; margin-bottom: 20px; }
      .hero h1 { margin: 0 0 8px; font-size: 32px; }
      .hero p { margin: 0; color: #5d6b81; }
      .hero-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; }
      .chips { display: flex; flex-wrap: wrap; gap: 8px; }
      .chip { border-radius: 999px; background: #fff; border: 1px solid #d6deea; padding: 8px 12px; font-size: 13px; color: #324057; box-shadow: 0 8px 20px rgba(22, 33, 51, 0.05); }
      .tabs { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 20px; }
      .tab, .btn, .ghost, .sort { border: 0; border-radius: 14px; cursor: pointer; transition: transform 0.15s ease; }
      .tab { background: #dfe7f1; color: #33425a; padding: 10px 16px; font-weight: 600; }
      .tab.active { background: #162133; color: #fff; box-shadow: 0 10px 22px rgba(22, 33, 51, 0.2); }
      .btn { background: #1f7a8c; color: #fff; padding: 12px 14px; font-weight: 600; }
      .ghost { background: #fff; color: #34445d; border: 1px solid #d6deea; padding: 10px 14px; }
      .sort { background: none; color: inherit; padding: 0; font: inherit; text-align: left; }
      .tab:hover, .btn:hover, .ghost:hover { transform: translateY(-1px); }
      .stack { display: flex; flex-direction: column; gap: 16px; }
      .grid { display: grid; gap: 16px; }
      .grid.two { grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }
      .grid.cards { grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
      .card { background: rgba(255, 255, 255, 0.95); border: 1px solid #dce4ef; border-radius: 20px; padding: 18px; box-shadow: 0 16px 32px rgba(22, 33, 51, 0.06); }
      .card h3 { margin: 0 0 14px; font-size: 18px; }
      .field, .toggle { display: flex; flex-direction: column; gap: 8px; font-size: 13px; color: #5d6b81; }
      .toggle { flex-direction: row; align-items: center; gap: 10px; color: #162133; }
      .toggle-row { display: flex; gap: 18px; margin-top: 12px; flex-wrap: wrap; }
      input, select { width: 100%; border: 1px solid #d4ddea; border-radius: 12px; padding: 10px 12px; box-sizing: border-box; background: #f9fbfd; color: #162133; }
      .button-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
      .status-list { display: flex; flex-direction: column; gap: 10px; }
      .status-row { display: flex; justify-content: space-between; gap: 16px; font-size: 14px; }
      .label { color: #5d6b81; }
      .value { text-align: right; }
      .muted { color: #6a7890; margin: 0; }
      .toolbar { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
      .toolbar-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
      .search { min-width: 260px; }
      .table-wrap { overflow: auto; border: 1px solid #dce4ef; border-radius: 16px; background: #fff; }
      table { width: 100%; border-collapse: collapse; min-width: 1200px; }
      th, td { padding: 10px 12px; border-bottom: 1px solid #edf1f6; vertical-align: top; text-align: left; font-size: 13px; }
      thead th { position: sticky; top: 0; background: #f7f9fc; z-index: 2; }
      .pill { display: inline-flex; align-items: center; border-radius: 999px; padding: 4px 10px; font-size: 12px; font-weight: 700; }
      .pill.ok { background: #dff6e7; color: #146c43; }
      .pill.bad { background: #fde4e4; color: #b42318; }
      .pill.info { background: #dceeff; color: #175cd3; }
      .pill.neutral { background: #edf2f7; color: #475467; }
      .warn { border-radius: 16px; background: #fff1d6; color: #8a5a00; border: 1px solid #ffd28a; padding: 14px 16px; display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
      .summary { margin: 0; padding-left: 20px; }
      .pager { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-top: 14px; flex-wrap: wrap; }
      .pager-btns { display: flex; gap: 8px; flex-wrap: wrap; }
      .empty { text-align: center; color: #6a7890; padding: 24px 16px; }
      @media (max-width: 900px) {
        .page { padding: 16px; }
        .hero { flex-direction: column; }
        .search { min-width: 0; width: 100%; }
      }
    </style>
    <div class="page">
      <section class="hero">
        <div>
          <h1>${escapeHtml(title)}</h1>
          <p>Zentrale Bedienung fuer Add-on, Status, Tests und Journal an einem Ort.</p>
          <div class="hero-actions">
            <button class="ghost" data-action="home">Zurueck zu Home Assistant</button>
            <button class="ghost" data-action="refresh">Journal neu laden</button>
          </div>
        </div>
        <div class="chips">
          <span class="chip">Run ID: ${formatValue(this.entity(ENTITIES.runSummary)?.state)}</span>
          <span class="chip">Journal: ${formatValue(journal.entry_count_total)}</span>
          <span class="chip">Tests: ${formatValue(this.entity(ENTITIES.tests)?.state)}</span>
        </div>
      </section>
      <nav class="tabs">${TABS.map(([key, label]) => `<button class="tab ${this.currentTab === key ? "active" : ""}" data-action="tab" data-tab="${key}">${escapeHtml(label)}</button>`).join("")}</nav>
      ${body}
    </div>`;
  }
}

if (!customElements.get(PANEL_NAME)) {
  customElements.define(PANEL_NAME, TradingAgentAdminPanel);
}
