const PANEL_NAME = "trading-agent-admin-panel";
const JOURNAL_URL = "/local/trading-agent/journal_table.json";
const REGISTRY_URL = "/local/trading-agent/asset_registry.json";
const HOME_URL = "/lovelace";
const PANEL_VERSION = "__PANEL_VERSION__";

const CHALLENGES_URL = "/local/trading-agent/challenges.json";
const PERSIST_OPERATOR_DEBOUNCE_MS = 400;
const TA_CHALLENGE_LS_KEY = "trading_agent_panel_challenge_id";
const TA_VIEWER_ENV_LS_KEY = "trading_agent_panel_view_env";

function envScopedUrl(base, env) {
  const safe = String(env || "").trim().toLowerCase();
  if (!safe) return base;
  const m = base.match(/^(.*)\.json$/);
  if (!m) return base;
  return `${m[1]}_${safe}.json`;
}

const ENTITIES = {
  addonSlug: "input_text.trading_agent_addon_slug",
  mode: "input_select.trading_agent_mode",
  environment: "input_select.trading_agent_environment",
  leverage: "input_number.trading_agent_leverage",
  markets: "input_text.trading_agent_markets",
  challengeId: "input_text.trading_agent_challenge_id",
  scheduleEnabled: "input_boolean.trading_agent_scheduling_aktiv",
  scheduleTime: "input_datetime.trading_agent_schedule_time",
  pushEnabled: "input_boolean.trading_agent_push_aktiv",
  operatorConfig: "sensor.trading_agent_operator_config",
  liveStatus: "sensor.trading_agent_live_status",
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

const LIFECYCLE_COLUMNS = [
  { key: "_expand", label: "", sortable: false },
  { key: "sort_timestamp", label: "Letzte Aktivitaet", sortable: true, filter: "text" },
  { key: "phase", label: "Phase", sortable: true, filter: "select", optionKey: "lifecycle_phases", badge: true },
  { key: "symbol", label: "Markt", sortable: true, filter: "select", optionKey: "symbols" },
  { key: "environment", label: "Umgebung", sortable: true, filter: "select", optionKey: "environments" },
  { key: "source_signal_type", label: "Signalquelle", sortable: true, filter: "select", optionKey: "signal_sources" },
  { key: "order_status", label: "Order-Status", sortable: true, filter: "text" },
  { key: "fill_timestamp", label: "Fill", sortable: true, filter: "text" },
  { key: "close_timestamp", label: "Exit", sortable: true, filter: "text" },
  { key: "management_count", label: "SL/TP Updates", sortable: true, filter: "text" },
  { key: "pnl", label: "PnL", sortable: true, filter: "text" },
];

const TRADE_COLUMNS = [
  { key: "_select", label: "", sortable: false },
  { key: "_expand", label: "", sortable: false },
  { key: "timestamp", label: "Zeit", sortable: true, filter: "text" },
  { key: "entry_type", label: "Typ", sortable: true, filter: "select", optionKey: "entry_types", badge: true },
  { key: "symbol", label: "Markt", sortable: true, filter: "select", optionKey: "symbols" },
  { key: "environment", label: "Umgebung", sortable: true, filter: "select", optionKey: "environments" },
  { key: "status", label: "Status", sortable: true, filter: "select", optionKey: "trade_statuses", badge: true },
  { key: "direction", label: "Richtung", sortable: true, filter: "select", optionKey: "directions", badge: true },
  { key: "source_signal_type", label: "Signalquelle", sortable: true, filter: "select", optionKey: "signal_sources" },
  { key: "position_size", label: "Groesse", sortable: true, filter: "text" },
  { key: "entry_price", label: "Entry", sortable: true, filter: "text" },
  { key: "stop_loss", label: "SL", sortable: true, filter: "text" },
  { key: "take_profit", label: "TP", sortable: true, filter: "text" },
  { key: "close_price", label: "Close", sortable: true, filter: "text" },
  { key: "pnl", label: "PnL", sortable: true, filter: "text" },
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

function firstPresent(obj, keys) {
  for (const key of keys) {
    const v = obj?.[key];
    if (v !== null && v !== undefined && v !== "") return v;
  }
  return null;
}

function formatCurrency(value) {
  if (value === null || value === undefined || value === "") return "-";
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return escapeHtml(value);
  return "$" + new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(numeric);
}

/** Plain-text markets summary for Status card (Steuerung-style counts when registry is loaded). */
function summarizeMarketsForStatusPanel(rawMarkets, registry) {
  const raw = String(rawMarkets ?? "").trim();
  if (!raw) return "-";
  const selected = new Set(raw.split(",").map((s) => s.trim()).filter(Boolean));
  if (!selected.size) return "-";
  if (!Array.isArray(registry) || !registry.length) {
    const tickers = [...selected];
    const preview = tickers.slice(0, 4).join(", ");
    const suffix = tickers.length > 4 ? "…" : "";
    return escapeHtml(`${tickers.length} Maerkte: ${preview}${suffix}`);
  }
  const crypto = registry.filter((a) => a.asset_type === "crypto");
  const hip3 = registry.filter((a) => a.asset_type === "hip3");
  let nCrypto = 0;
  let nHip3 = 0;
  for (const a of crypto) {
    if (selected.has(a.name) || selected.has(a.propr_asset)) nCrypto += 1;
  }
  for (const a of hip3) {
    if (selected.has(a.name) || selected.has(a.propr_asset)) nHip3 += 1;
  }
  const parts = [];
  if (nCrypto) parts.push(`${nCrypto} Crypto Perps`);
  if (nHip3) parts.push(`${nHip3} Stocks & Commodities`);
  if (!parts.length) {
    const tickers = [...selected];
    const preview = tickers.slice(0, 4).join(", ");
    const suffix = tickers.length > 4 ? "…" : "";
    return escapeHtml(`${tickers.length} Maerkte: ${preview}${suffix}`);
  }
  return escapeHtml(`${selected.size} ausgewaehlt (${parts.join(", ")})`);
}

function formatPnl(value) {
  if (value === null || value === undefined || value === "") return "-";
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return escapeHtml(value);
  const formatted = new Intl.NumberFormat("de-CH", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    signDisplay: "always",
  }).format(numeric);
  const cls = numeric > 0 ? "pnl-pos" : numeric < 0 ? "pnl-neg" : "";
  return cls ? `<span class="${cls}">${formatted}</span>` : formatted;
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

function decisionBadgeClass(value) {
  const v = String(value ?? "").toLowerCase();
  if (v.startsWith("prepare_") || v === "close_trend_and_prepare_countertrend") return "action";
  if (v === "close_trend_trade") return "close";
  if (v.startsWith("adjust_")) return "info";
  return "neutral";
}

function buildLifecycleChains(tradeRows) {
  const byId = new Map();
  const ungrouped = [];
  for (const row of tradeRows) {
    if (row.lifecycle_id) {
      if (!byId.has(row.lifecycle_id)) byId.set(row.lifecycle_id, []);
      byId.get(row.lifecycle_id).push(row);
    } else {
      ungrouped.push(row);
    }
  }
  const bySymbol = new Map();
  for (const row of [...ungrouped].sort((a, b) => (a.timestamp || "").localeCompare(b.timestamp || ""))) {
    const sym = row.symbol || "_";
    if (!bySymbol.has(sym)) bySymbol.set(sym, [[]]);
    const chains = bySymbol.get(sym);
    chains[chains.length - 1].push(row);
    if (row.status === "closed") chains.push([]);
  }
  const lifecycles = [];
  for (const chain of byId.values()) {
    lifecycles.push(chain.sort((a, b) => (a.timestamp || "").localeCompare(b.timestamp || "")));
  }
  for (const chains of bySymbol.values()) {
    for (const chain of chains) {
      if (chain.length > 0) lifecycles.push(chain);
    }
  }
  return lifecycles;
}

function buildLifecycleDetail(row) {
  const steps = row.steps || [];
  if (!steps.length) {
    return `<div class="detail-grid"><div class="muted">Keine Schritte erfasst.</div></div>`;
  }
  const lines = steps.map((s) => {
    const kind = escapeHtml(s.step || "");
    const at = formatValue(s.at);
    const extra = Object.entries(s)
      .filter(([k]) => !["step", "at"].includes(k))
      .map(([k, v]) => `${escapeHtml(k)}: ${escapeHtml(v != null ? String(v) : "-")}`)
      .join(" · ");
    return `<div class="event-item"><span class="event-time">${at}</span><span class="pill neutral">${kind}</span> ${extra ? `<span class="event-note">${extra}</span>` : ""}</div>`;
  });
  return `<div class="event-log"><h4>Lifecycle-Schritte</h4>${lines.join("")}</div>`;
}

function buildTradeDetail(row, allTradeRows) {
  const details = `<div class="detail-grid">
    <div><span class="detail-label">Fill-Zeit</span> ${formatValue(row.fill_timestamp)}</div>
    <div><span class="detail-label">Close-Zeit</span> ${formatValue(row.close_timestamp)}</div>
    <div><span class="detail-label">Notizen</span> ${escapeHtml(row.notes ?? "-")}</div>
  </div>`;
  const chains = buildLifecycleChains(allTradeRows);
  const chain = chains.find((c) => c.some((r) =>
    r.timestamp === row.timestamp && r.symbol === row.symbol && r.entry_type === row.entry_type && r.status === row.status
  )) || [];
  const related = chain.filter((r) =>
    !(r.timestamp === row.timestamp && r.entry_type === row.entry_type && r.status === row.status)
  );
  if (!related.length) return details;
  const events = related.map((r) => `<div class="event-item">
    <span class="event-time">${formatValue(r.timestamp)}</span>
    <span class="pill ${badgeClass(r.status)}">${escapeHtml(r.entry_type ?? "")}: ${escapeHtml(r.status ?? "")}</span>
    ${r.entry_price != null ? `<span>Entry: ${escapeHtml(String(r.entry_price))}</span>` : ""}
    ${r.stop_loss != null ? `<span>SL: ${escapeHtml(String(r.stop_loss))}</span>` : ""}
    ${r.take_profit != null ? `<span>TP: ${escapeHtml(String(r.take_profit))}</span>` : ""}
    ${r.close_price != null ? `<span>Close: ${escapeHtml(String(r.close_price))}</span>` : ""}
    ${r.pnl != null ? `<span>PnL: ${formatPnl(r.pnl)}</span>` : ""}
    ${r.notes ? `<span class="event-note">${escapeHtml(r.notes)}</span>` : ""}
  </div>`).join("");
  return `${details}<div class="event-log"><h4>Ereignis-Verlauf</h4>${events}</div>`;
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

function buildFilterOptions(scanRows, tradeRows, lifecycleRows) {
  const lr = lifecycleRows || [];
  const allRows = [...scanRows, ...tradeRows, ...lr];
  return {
    symbols: uniqueValues(allRows, "symbol"),
    environments: uniqueValues(allRows, "environment"),
    decision_actions: uniqueValues(scanRows, "decision_action"),
    scan_signals: uniqueValues(scanRows, "selected_signal_type"),
    signal_types: uniqueValues(scanRows, "signal_type"),
    entry_types: uniqueValues(tradeRows, "entry_type"),
    trade_statuses: uniqueValues(tradeRows, "status"),
    directions: uniqueValues(tradeRows, "direction"),
    signal_sources: uniqueValues(tradeRows, "source_signal_type"),
    lifecycle_phases: uniqueValues(lr, "phase"),
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
function _deriveScanSignalType(signalType) {
  if (!signalType) return "Kein Signal";
  const upper = String(signalType).toUpperCase();
  if (upper.startsWith("TREND_")) return "Trend";
  if (upper.startsWith("COUNTERTREND_")) return "Gegentrend";
  return "Kein Signal";
}

function snapshotFallback(journalState) {
  const recentEntries = journalState?.attributes?.recent_entries || [];
  const scanRows = recentEntries
    .filter((entry) => entry.entry_type === "cycle")
    .map((entry) => ({
      executed_at: entry.executed_at || null,
      timestamp: entry.entry_timestamp || null,
      entry_date: entry.entry_date || null,
      symbol: entry.symbol || null,
      environment: entry.environment || null,
      decision_action: entry.decision_action || null,
      selected_signal_type: entry.source_signal_type || null,
      signal_type: _deriveScanSignalType(entry.source_signal_type),
      received_signals: entry.source_signal_type || null,
      order_created: false,
      order_status_summary: null,
      trade_status_summary: null,
      trade_pnl_summary: entry.pnl ?? null,
      skip_reason: entry.skipped_reason || null,
      notes: entry.notes || null,
      display_reason: (entry.notes && entry.skipped_reason)
        ? `${entry.notes} • not executed: ${entry.skipped_reason}`
        : (entry.notes || entry.skipped_reason || null),
      related_order_count: 0,
      related_trade_count: 0,
      entry_price: null,
      fill_time: null,
      tp: null,
      sl: null,
      exit_price: null,
      exit_time: null,
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
      entry_price: entry.entry_price ?? null,
      stop_loss: entry.stop_loss ?? null,
      take_profit: entry.take_profit ?? null,
      close_price: entry.close_price ?? null,
      lifecycle_id: entry.lifecycle_id ?? null,
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
      lifecycle_rows: [],
      filter_options: buildFilterOptions([], [], []),
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
    lifecycle_rows: [],
    filter_options: buildFilterOptions(scanRows, tradeRows, []),
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
      lifecycle_rows: [],
      filter_options: buildFilterOptions([], [], []),
      warnings: [],
    };
    this.loadError = null;
    this.loading = false;
    this.lastRunId = null;
    this.tableState = {
      scans: { ...BASE_TABLE_STATE },
      trades: { ...BASE_TABLE_STATE },
      lifecycle: { ...BASE_TABLE_STATE, sortKey: "sort_timestamp" },
    };
    this._directLiveStatus = null;
    this._liveStatusInterval = null;
    this._lastJournalRefresh = 0;
    this._expandedTradeRows = new Set();
    this._expandedLifecycleRows = new Set();
    this._selectedTradeRows = new Set();
    this._expandedScanRuns = new Set();
    this.assetRegistry = null;
    this.challengesList = null;
    this._marketGroupsExpanded = {};
    this._marketFilter = "";
    this._persistOperatorTimer = null;
    this._challengeHydrateAttempted = false;
    this._onVisibilityChange = () => { if (!document.hidden && this._liveStatusInterval) this._fetchLiveStatus(); };
    this._viewerEnv = null;
    this._stateByEnv = {};
  }
  connectedCallback() {
    this.shadowRoot.addEventListener("click", (event) => this.onClick(event));
    this.shadowRoot.addEventListener("change", (event) => this.onChange(event));
    this.shadowRoot.addEventListener("input", (event) => this.onInput(event));
    document.addEventListener("visibilitychange", this._onVisibilityChange);
    this.refreshJournal();
    this.fetchAssetRegistry();
    this.fetchChallenges();
    this.render();
  }

  disconnectedCallback() {
    document.removeEventListener("visibilitychange", this._onVisibilityChange);
    this._stopLivePolling();
    if (this._persistOperatorTimer != null) {
      clearTimeout(this._persistOperatorTimer);
      this._persistOperatorTimer = null;
    }
  }

  _startLivePolling() {
    if (this._liveStatusInterval) return;
    this._fetchLiveStatus();
    this._liveStatusInterval = setInterval(() => { if (!document.hidden) this._fetchLiveStatus(); }, 10_000);
  }

  _stopLivePolling() {
    if (!this._liveStatusInterval) return;
    clearInterval(this._liveStatusInterval);
    this._liveStatusInterval = null;
  }

  async _fetchLiveStatus() {
    try {
      const env = this.viewerEnv();
      const primaryUrl = envScopedUrl("/local/trading-agent/live_status.json", env);
      const resp = await fetch(`${primaryUrl}?ts=${Date.now()}`, { cache: "no-store" });
      if (resp.ok) {
        this._directLiveStatus = await resp.json();
        this.render();
      } else if (primaryUrl !== "/local/trading-agent/live_status.json") {
        const fallback = await fetch(`/local/trading-agent/live_status.json?ts=${Date.now()}`, { cache: "no-store" });
        if (fallback.ok) {
          this._directLiveStatus = await fallback.json();
          this.render();
        }
      }
    } catch (_) {}
    this._checkPanelVersion();
  }

  async _checkPanelVersion() {
    try {
      const resp = await fetch(`/local/trading-agent/panel_version.txt?_=${Date.now()}`, { cache: "no-store" });
      if (!resp.ok) return;
      const latest = (await resp.text()).trim();
      if (latest && PANEL_VERSION !== "__PANEL_VERSION__" && latest !== PANEL_VERSION) {
        const reloadKey = `__ta_panel_reload_${latest}`;
        if (sessionStorage.getItem(reloadKey)) return;
        sessionStorage.setItem(reloadKey, "1");
        console.info("[Trading Agent] Panel update:", PANEL_VERSION, "\u2192", latest);
        window.location.reload();
      }
    } catch (_) {}
  }

  _effectiveLiveData() {
    if (this._directLiveStatus) return this._directLiveStatus;
    const entity = this.entity(ENTITIES.liveStatus);
    if (!entity) return null;
    return {
      account_unrealized_pnl: entity.attributes?.account_unrealized_pnl,
      account_open_positions_count: entity.attributes?.account_open_positions_count,
      websocket_connected: entity.attributes?.websocket_connected,
      source: entity.state,
      last_error: entity.attributes?.last_error,
      updated_at: entity.attributes?.updated_at,
      challenge_name: entity.attributes?.challenge_name,
      challenge_id: entity.attributes?.challenge_id,
      initial_balance: entity.attributes?.initial_balance,
      balance: entity.attributes?.balance,
      margin_balance: entity.attributes?.margin_balance,
      available_balance: entity.attributes?.available_balance,
      high_water_mark: entity.attributes?.high_water_mark,
      open_positions_summary: entity.attributes?.open_positions_summary,
      challenges_overview: entity.attributes?.challenges_overview,
      active_challenges_count: entity.attributes?.active_challenges_count,
      account_total_margin_balance: entity.attributes?.account_total_margin_balance,
    };
  }

  set hass(value) {
    this.hassState = value;
    // Initialize viewer environment (separate from operator env).
    if (!this._viewerEnv) {
      try {
        const stored = (typeof localStorage !== "undefined" && localStorage.getItem(TA_VIEWER_ENV_LS_KEY)) || "";
        this._viewerEnv = stored.trim() || null;
      } catch (_) {}
    }
    if (!this._viewerEnv) {
      const opEnv = value?.states?.[ENTITIES.operatorConfig]?.attributes?.environment
        || value?.states?.[ENTITIES.environment]?.state
        || "";
      this._viewerEnv = String(opEnv || "").trim() || "beta";
    }
    const runId = value?.states?.[ENTITIES.runSummary]?.state;
    if (runId && !["unknown", "unavailable"].includes(runId) && runId !== this.lastRunId) {
      this.lastRunId = runId;
      this.refreshJournal();
    }
    if (value && !this._challengeHydrateAttempted) {
      this._challengeHydrateAttempted = true;
      try {
        const stored = (typeof localStorage !== "undefined" && localStorage.getItem(TA_CHALLENGE_LS_KEY)) || "";
        const cur = String(value.states?.[ENTITIES.challengeId]?.state ?? "").trim();
        if (!cur && stored.trim()) {
          this.setEntityValue(ENTITIES.challengeId, stored.trim()).then(() => this._schedulePersistOperatorConfig());
        }
      } catch (_) {
        /* ignore */
      }
    }
    this.render();
  }

  viewerEnv() {
    return String(this._viewerEnv || "").trim() || "beta";
  }

  _setViewerEnv(nextEnv) {
    const env = String(nextEnv || "").trim().toLowerCase();
    if (!env || env === this.viewerEnv()) return;
    // Persist per-env UI state.
    const cur = this.viewerEnv();
    this._stateByEnv[cur] = {
      tableState: this.tableState,
      expandedTradeRows: this._expandedTradeRows,
      expandedLifecycleRows: this._expandedLifecycleRows,
      selectedTradeRows: this._selectedTradeRows,
      expandedScanRuns: this._expandedScanRuns,
      marketGroupsExpanded: this._marketGroupsExpanded,
      marketFilter: this._marketFilter,
    };
    const restore = this._stateByEnv[env];
    if (restore) {
      this.tableState = restore.tableState;
      this._expandedTradeRows = restore.expandedTradeRows;
      this._expandedLifecycleRows = restore.expandedLifecycleRows;
      this._selectedTradeRows = restore.selectedTradeRows;
      this._expandedScanRuns = restore.expandedScanRuns;
      this._marketGroupsExpanded = restore.marketGroupsExpanded;
      this._marketFilter = restore.marketFilter;
    } else {
      this.tableState = {
        scans: { ...BASE_TABLE_STATE },
        trades: { ...BASE_TABLE_STATE },
        lifecycle: { ...BASE_TABLE_STATE, sortKey: "sort_timestamp" },
      };
      this._expandedTradeRows = new Set();
      this._expandedLifecycleRows = new Set();
      this._selectedTradeRows = new Set();
      this._expandedScanRuns = new Set();
      this._marketGroupsExpanded = {};
      this._marketFilter = "";
    }
    this._viewerEnv = env;
    try {
      if (typeof localStorage !== "undefined") localStorage.setItem(TA_VIEWER_ENV_LS_KEY, env);
    } catch (_) {}
    this._directLiveStatus = null;
    this.refreshJournal();
    this.fetchChallenges();
    if (this._liveStatusInterval) this._fetchLiveStatus();
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
    this._lastJournalRefresh = Date.now();
    this.render();
    try {
      const env = this.viewerEnv();
      const primaryUrl = envScopedUrl(JOURNAL_URL, env);
      const response = await fetch(`${primaryUrl}?ts=${Date.now()}`, { cache: "no-store" });
      if (response.ok) {
        this.journalPayload = await response.json();
      } else if (primaryUrl !== JOURNAL_URL) {
        const fallback = await fetch(`${JOURNAL_URL}?ts=${Date.now()}`, { cache: "no-store" });
        if (!fallback.ok) throw new Error(`HTTP ${fallback.status}`);
        this.journalPayload = await fallback.json();
        this.journalPayload = {
          ...this.journalPayload,
          warnings: [
            ...(this.journalPayload.warnings || []),
            `Viewer env '${env}' konnte nicht env-spezifisch geladen werden (${primaryUrl}). Fallback auf legacy ${JOURNAL_URL}.`,
          ],
        };
      } else {
        throw new Error(`HTTP ${response.status}`);
      }
    } catch (error) {
      this.loadError = error instanceof Error ? error.message : String(error);
    } finally {
      this.loading = false;
      this.render();
    }
  }

  async fetchAssetRegistry() {
    try {
      const resp = await fetch(`${REGISTRY_URL}?ts=${Date.now()}`, { cache: "no-store" });
      if (resp.ok) {
        const data = await resp.json();
        this.assetRegistry = data.assets || [];
        this.render();
      }
    } catch (_) {}
  }

  async fetchChallenges() {
    try {
      const env = this.viewerEnv();
      const primaryUrl = envScopedUrl(CHALLENGES_URL, env);
      const resp = await fetch(`${primaryUrl}?ts=${Date.now()}`, { cache: "no-store" });
      if (resp.ok) {
        this.challengesList = await resp.json();
        this.render();
      } else if (primaryUrl !== CHALLENGES_URL) {
        const fallback = await fetch(`${CHALLENGES_URL}?ts=${Date.now()}`, { cache: "no-store" });
        if (fallback.ok) {
          this.challengesList = await fallback.json();
          this.render();
        }
      }
    } catch (_) {}
  }

  challengeSelector() {
    const challenges = this.challengesList;
    const currentRaw = this.entity(ENTITIES.challengeId)?.state || "";
    const currentId = String(currentRaw || "").trim();
    if (!challenges || !challenges.length) {
      return this.field(ENTITIES.challengeId, "text", { label: "Challenge Attempt ID" });
    }

    // Backwards compatibility: older versions stored challenge_id in the helper. We now store attempt_id.
    // If the helper contains a challenge_id, upgrade it to the first matching attempt_id deterministically.
    const attemptIds = new Set(challenges.map((c) => String(c.attempt_id || "").trim()).filter(Boolean));
    const hasAttemptMatch = currentId && attemptIds.has(currentId);
    if (currentId && !hasAttemptMatch) {
      const upgrade = challenges.find((c) => String(c.challenge_id || "").trim() === currentId && String(c.attempt_id || "").trim());
      if (upgrade) {
        const upgradedAttemptId = String(upgrade.attempt_id).trim();
        // Fire-and-forget: keep UI consistent and persist operator config.
        this.setEntityValue(ENTITIES.challengeId, upgradedAttemptId).then(() => this._schedulePersistOperatorConfig());
      }
    }

    const effectiveId = hasAttemptMatch ? currentId : "";
    const options = [
      `<option value="" ${!effectiveId ? "selected" : ""}>-- Automatisch (erste aktive) --</option>`,
      ...challenges.map((c) => {
        const bal = c.initial_balance ? ` ($${Number(c.initial_balance).toLocaleString("en-US")})` : "";
        const label = `${escapeHtml(c.name || c.challenge_id)}${bal}`;
        const attemptId = String(c.attempt_id || "").trim();
        const selected = attemptId && attemptId === effectiveId ? "selected" : "";
        return `<option value="${escapeHtml(attemptId)}" ${selected}>${label}</option>`;
      }),
    ].join("");
    return `<label class="field"><span>Challenge</span><select data-entity="${ENTITIES.challengeId}">${options}</select></label>`;
  }

  _currentMarketSelection() {
    const state = this.entity(ENTITIES.markets);
    const raw = state?.state ?? "";
    return new Set(raw.split(",").map((s) => s.trim()).filter(Boolean));
  }

  async _updateMarketSelection(selected) {
    const value = [...selected].join(",");
    await this.setEntityValue(ENTITIES.markets, value);
  }

  _schedulePersistOperatorConfig() {
    if (this._persistOperatorTimer != null) {
      clearTimeout(this._persistOperatorTimer);
    }
    this._persistOperatorTimer = setTimeout(() => {
      this._persistOperatorTimer = null;
      this.callService("script", "turn_on", { entity_id: "script.trading_agent_save_current_config_haos" });
    }, PERSIST_OPERATOR_DEBOUNCE_MS);
  }

  marketsSelector() {
    const registry = this.assetRegistry;
    if (!registry || !registry.length) {
      return this.field(ENTITIES.markets);
    }
    const selected = this._currentMarketSelection();
    const filter = this._marketFilter.toLowerCase();

    const crypto = registry.filter((a) => a.asset_type === "crypto");
    const hip3 = registry.filter((a) => a.asset_type === "hip3");

    const filteredCrypto = filter ? crypto.filter((a) => a.name.toLowerCase().includes(filter)) : crypto;
    const filteredHip3 = filter ? hip3.filter((a) => a.name.toLowerCase().includes(filter) || a.propr_asset.toLowerCase().includes(filter)) : hip3;

    const cryptoExpanded = this._marketGroupsExpanded.crypto;
    const hip3Expanded = this._marketGroupsExpanded.hip3;

    const selectedCryptoCount = crypto.filter((a) => selected.has(a.name) || selected.has(a.propr_asset)).length;
    const selectedHip3Count = hip3.filter((a) => selected.has(a.name) || selected.has(a.propr_asset)).length;
    const totalSelected = selectedCryptoCount + selectedHip3Count;

    const checkboxGrid = (assets, useProprAsset) =>
      assets.map((a) => {
        const val = useProprAsset ? a.propr_asset : a.name;
        const checked = selected.has(a.name) || selected.has(a.propr_asset) ? "checked" : "";
        const label = useProprAsset ? `${a.name}` : a.name;
        return `<label class="market-item"><input type="checkbox" data-market-asset="${escapeHtml(val)}" ${checked}><span>${escapeHtml(label)}</span></label>`;
      }).join("");

    return `<div class="market-selector">
      <label class="field"><span>Maerkte (${totalSelected} ausgewaehlt)</span></label>
      <input type="text" class="market-search" data-market-filter placeholder="Filter..." value="${escapeHtml(this._marketFilter)}">
      <div class="market-group">
        <div class="market-group-header" data-action="toggle-market-group" data-group="crypto">
          <span>${cryptoExpanded ? "&#9660;" : "&#9654;"} Crypto Perps (${crypto.length})${selectedCryptoCount > 0 ? ` — ${selectedCryptoCount} ausgewaehlt` : ""}</span>
        </div>
        ${cryptoExpanded ? `<div class="market-checkbox-grid">${filteredCrypto.length ? checkboxGrid(filteredCrypto, false) : '<span class="muted">Keine Treffer</span>'}</div>` : ""}
      </div>
      <div class="market-group">
        <div class="market-group-header" data-action="toggle-market-group" data-group="hip3">
          <span>${hip3Expanded ? "&#9660;" : "&#9654;"} Stocks &amp; Commodities (${hip3.length})${selectedHip3Count > 0 ? ` — ${selectedHip3Count} ausgewaehlt` : ""}</span>
        </div>
        ${hip3Expanded ? `<div class="market-checkbox-grid">${filteredHip3.length ? checkboxGrid(filteredHip3, true) : '<span class="muted">Keine Treffer</span>'}</div>` : ""}
      </div>
    </div>`;
  }

  async _deleteSelectedTrades() {
    const journal = this.effectiveJournal();
    const tradeRows = journal.trade_rows || [];
    const entries = [];
    for (const idx of this._selectedTradeRows) {
      const row = tradeRows[idx];
      if (row) {
        entries.push({
          entry_timestamp: row.timestamp,
          symbol: row.symbol,
          environment: row.environment || this.viewerEnv(),
          entry_type: row.entry_type,
          status: row.status,
        });
      }
    }
    if (!entries.length) return;
    try {
      await this.hass.callService("shell_command", "trading_agent_delete_journal_entries_haos", {
        entries: JSON.stringify(entries),
      });
      this._selectedTradeRows.clear();
      this._expandedTradeRows.clear();
      await new Promise((r) => setTimeout(r, 1000));
      await this.refreshJournal();
    } catch (err) {
      console.error("[Trading Agent] Delete failed:", err);
    }
  }

  effectiveJournal() {
    const live = this.journalPayload || {};
    if (
      (live.entry_count_total || 0) > 0 ||
      (live.scan_rows?.length || 0) > 0 ||
      (live.trade_rows?.length || 0) > 0 ||
      (live.lifecycle_rows?.length || 0) > 0
    ) {
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
        ([label, value, useBadge, formatter]) =>
          `<div class="status-row"><span class="label">${escapeHtml(label)}</span><span class="value">${
            useBadge ? `<span class="pill ${badgeClass(value)}">${formatter ? formatter(value) : formatValue(value)}</span>` : formatter ? formatter(value) : formatValue(value)
          }</span></div>`
      )
      .join("")}</div></section>`;
  }
  controlsTab() {
    const viewerEnv = this.viewerEnv();
    const envOptions = this.entity(ENTITIES.environment)?.attributes?.options || ["beta", "prod"];
    const viewerSelector = `<label class="field"><span>Viewer Umgebung</span><select data-viewer-env="1">${
      envOptions.map((opt) => `<option value="${escapeHtml(opt)}" ${String(opt).toLowerCase() === viewerEnv ? "selected" : ""}>${escapeHtml(opt)}</option>`).join("")
    }</select></label>`;
    return `<div class="stack">
      <section class="card">
        <h3>Operator</h3>
        <div class="grid two">
          ${viewerSelector}
          ${this.field(ENTITIES.mode, "select")}
          ${this.field(ENTITIES.environment, "select")}
          ${this.field(ENTITIES.leverage, "number")}
          ${this.field(ENTITIES.scheduleTime, "time")}
          ${this.challengeSelector()}
          ${this.field(ENTITIES.addonSlug)}
        </div>
        ${this.marketsSelector()}
        <div class="toggle-row">
          ${this.field(ENTITIES.scheduleEnabled, "checkbox")}
          ${this.field(ENTITIES.pushEnabled, "checkbox")}
        </div>
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
    const ld = this._effectiveLiveData();
    const runSummary = this.entity(ENTITIES.runSummary);
    const tests = this.entity(ENTITIES.tests);
    const journalSensor = this.entity(ENTITIES.journal);
    const summaryLines = runSummary?.attributes?.summary_lines || [];

    // Active position: latest "filled" trade row from journal, else WebSocket summary
    const openTrade = (journal.trade_rows || []).find((r) => r.entry_type === "trade" && r.status === "filled");
    const wsPositions = Array.isArray(ld?.open_positions_summary) ? ld.open_positions_summary : [];
    const openPositions = Number(ld?.account_open_positions_count ?? 0);
    const wsDetailRows = (!openTrade && wsPositions.length)
      ? wsPositions.map((p, idx) => {
        const stopLoss = firstPresent(p, ["stop_loss", "stopLoss", "sl", "internal_stop_loss"]);
        const takeProfit = firstPresent(p, ["take_profit", "takeProfit", "tp", "internal_take_profit"]);
        const entryPrice = firstPresent(p, ["entry_price", "entryPrice", "entry"]);
        const positionSize = firstPresent(p, ["position_size", "positionSize", "size"]);
        return `<div class="${idx ? "ws-pos-block" : ""}">
            ${p.challenge_name ? `<div class="status-row"><span class="label">Challenge</span><span class="value">${escapeHtml(p.challenge_name)}</span></div>` : ""}
            <div class="status-row"><span class="label">Markt</span><span class="value">${escapeHtml(p.symbol ?? "-")}</span></div>
            <div class="status-row"><span class="label">Richtung</span><span class="value"><span class="pill ${badgeClass(p.direction)}">${escapeHtml(p.direction ?? "-")}</span></span></div>
            <div class="status-row"><span class="label">Groesse</span><span class="value">${positionSize != null ? escapeHtml(String(positionSize)) : "-"}</span></div>
            <div class="status-row"><span class="label">Entry</span><span class="value">${entryPrice != null ? escapeHtml(String(entryPrice)) : "-"}</span></div>
            <div class="status-row"><span class="label">Stop Loss</span><span class="value">${stopLoss != null ? escapeHtml(String(stopLoss)) : "-"}</span></div>
            <div class="status-row"><span class="label">Take Profit</span><span class="value">${takeProfit != null ? escapeHtml(String(takeProfit)) : "-"}</span></div>
            ${p.unrealized_pnl != null ? `<div class="status-row"><span class="label">Position PnL</span><span class="value">${formatPnl(p.unrealized_pnl)}</span></div>` : ""}
            </div>`;
      }).join("")
      : "";
    const cov = Array.isArray(ld?.challenges_overview) ? ld.challenges_overview : [];
    const multiChallengeRows = cov.length > 1
      ? cov.map((c) => `<tr>
          <td>${escapeHtml(c.challenge_name ?? c.challenge_id ?? c.account_id ?? "-")}</td>
          <td class="num">${formatPnl(c.account_unrealized_pnl)}</td>
          <td class="num">${formatCurrency(c.margin_balance)}</td>
          <td class="num">${escapeHtml(String(c.account_open_positions_count ?? 0))}</td>
        </tr>`).join("")
      : "";
    const allChallengesCard = cov.length > 1
      ? `<section class="card">
          <h3>Alle aktiven Challenges (${cov.length})</h3>
          <p class="muted">Summe unrealisiertes PnL und alle offenen Positionen ueber alle Challenge-Konten (REST nach jedem Add-on-Lauf).</p>
          <table class="overview-table">
            <thead><tr><th>Challenge</th><th class="num">Unreal. PnL</th><th class="num">Margin</th><th class="num">Offene Pos.</th></tr></thead>
            <tbody>${multiChallengeRows}</tbody>
          </table>
        </section>`
      : "";

    const activePositionCard = (openPositions > 0 || openTrade)
      ? `<section class="card card-highlight card-narrow">
          <h3>Offene Positionen ${openPositions > 1 || cov.length > 1 ? `(${openPositions})` : ""}</h3>
          <div class="status-list">
            <div class="status-row"><span class="label">Unrealisiertes PnL</span><span class="value pnl-live">${formatPnl(ld?.account_unrealized_pnl)}</span></div>
            ${openTrade ? `
            <div class="status-row"><span class="label">Richtung</span><span class="value"><span class="pill ${badgeClass(openTrade.direction)}">${escapeHtml(openTrade.direction ?? "-")}</span></span></div>
            <div class="status-row"><span class="label">Groesse</span><span class="value">${escapeHtml(String(openTrade.position_size ?? "-"))}</span></div>
            <div class="status-row"><span class="label">Entry</span><span class="value">${openTrade.entry_price != null ? escapeHtml(String(openTrade.entry_price)) : "-"}</span></div>
            <div class="status-row"><span class="label">Stop Loss</span><span class="value">${openTrade.stop_loss != null ? escapeHtml(String(openTrade.stop_loss)) : "-"}</span></div>
            <div class="status-row"><span class="label">Take Profit</span><span class="value">${openTrade.take_profit != null ? escapeHtml(String(openTrade.take_profit)) : "-"}</span></div>
            ` : wsDetailRows}
            <div class="status-row"><span class="label">Quelle</span><span class="value"><span class="pill ${badgeClass(ld?.source)}">${escapeHtml(ld?.source ?? "-")}</span></span></div>
            <div class="status-row"><span class="label">Aktualisiert</span><span class="value">${formatValue(ld?.updated_at)}</span></div>
          </div>
        </section>`
      : "";

    // Challenge account card
    const hasBalanceData = ld?.margin_balance != null || ld?.balance != null;
    const challengeReturn = (ld?.margin_balance != null && ld?.initial_balance)
      ? ((ld.margin_balance - ld.initial_balance) / ld.initial_balance * 100).toFixed(2) : null;
    const challengeAccountCard = hasBalanceData
      ? `<section class="card">
          <h3>Challenge Konto</h3>
          <div class="status-list">
            ${ld?.challenge_name ? `<div class="status-row"><span class="label">Challenge</span><span class="value">${escapeHtml(ld.challenge_name)}</span></div>` : ""}
            <div class="status-row"><span class="label">Saldo</span><span class="value">${formatCurrency(ld?.balance)}</span></div>
            <div class="status-row"><span class="label">Margin Balance</span><span class="value">${formatCurrency(ld?.margin_balance)}</span></div>
            <div class="status-row"><span class="label">Verfuegbar</span><span class="value">${formatCurrency(ld?.available_balance)}</span></div>
            <div class="status-row"><span class="label">High Water Mark</span><span class="value">${formatCurrency(ld?.high_water_mark)}</span></div>
            <div class="status-row"><span class="label">Startkapital</span><span class="value">${formatCurrency(ld?.initial_balance)}</span></div>
            ${challengeReturn != null ? `<div class="status-row"><span class="label">Rendite</span><span class="value ${Number(challengeReturn) >= 0 ? "pnl-pos" : "pnl-neg"}">${Number(challengeReturn) >= 0 ? "+" : ""}${challengeReturn}%</span></div>` : ""}
          </div>
        </section>`
      : "";

    // Stats from journal
    const closedTrades = (journal.trade_rows || []).filter((r) => r.entry_type === "trade" && r.status === "closed");
    const winningTrades = closedTrades.filter((r) => r.pnl != null && Number(r.pnl) > 0);
    const totalPnl = closedTrades.reduce((sum, r) => sum + (Number(r.pnl) || 0), 0);
    const winRate = closedTrades.length ? (winningTrades.length / closedTrades.length * 100).toFixed(1) : null;
    const statsStrip = closedTrades.length > 0
      ? `<div class="stats-strip">
          <div class="stat-tile"><div class="stat-value">${closedTrades.length}</div><div class="stat-label">Abgeschl. Trades</div></div>
          <div class="stat-tile"><div class="stat-value">${winningTrades.length}</div><div class="stat-label">Gewinner</div></div>
          <div class="stat-tile"><div class="stat-value">${winRate}%</div><div class="stat-label">Trefferquote</div></div>
          <div class="stat-tile"><div class="stat-value ${totalPnl > 0 ? "pnl-pos" : totalPnl < 0 ? "pnl-neg" : ""}">${formatPnl(totalPnl)}</div><div class="stat-label">Realisiertes PnL</div></div>
        </div>`
      : "";

    const marketsSummaryHtml = summarizeMarketsForStatusPanel(operator?.attributes?.markets, this.assetRegistry);
    return `<div class="stack">
      ${allChallengesCard}
      ${activePositionCard}
      ${challengeAccountCard}
      ${statsStrip}
      <div class="grid cards">
        ${this.statusCard("Operator Config", [
          ["Modus", operator?.state, true],
          ["Umgebung", operator?.attributes?.environment, true],
          ["Leverage", operator?.attributes?.leverage],
          ["Maerkte", operator?.attributes?.markets, false, () => marketsSummaryHtml],
          ["Scheduling", operator?.attributes?.scheduling_enabled],
          ["Zeit", operator?.attributes?.schedule_time],
        ])}
        ${this.statusCard("Live-Status", [
          ["PnL (Summe)", ld?.account_unrealized_pnl, false, formatPnl],
          ["Offene Positionen (Summe)", ld?.account_open_positions_count],
          ...(ld?.account_total_margin_balance != null && ld?.account_total_margin_balance !== ""
            ? [["Gesamt Margin (Konten)", ld?.account_total_margin_balance, false, formatCurrency]]
            : []),
          ...(Number(ld?.active_challenges_count) > 1
            ? [["Aktive Challenges", ld?.active_challenges_count]]
            : []),
          ["Quelle", ld?.source, true],
          ["WebSocket verbunden", ld?.websocket_connected, true],
          ["Letztes Update", ld?.updated_at],
          ["Letzter Fehler", ld?.last_error],
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
  scansTab() {
    const journal = this.effectiveJournal();
    const flatScanRows = journal.scan_rows || [];
    const state = this.tableState.scans;
    const search = (state.search || "").trim().toLowerCase();
    const envFilter = (state.filters.environment || "").toLowerCase();

    // Group flat per-market rows into runs: (runTime, environment)
    const runMap = new Map();
    for (const row of flatScanRows) {
      const runTime = row.executed_at || row.timestamp || "";
      const runKey = `${runTime}_${row.environment}`;
      if (!runMap.has(runKey)) {
        runMap.set(runKey, {
          executed_at: runTime,
          environment: row.environment,
          signals: 0,
          orders_created: 0,
          trades_managed: 0,
          markets: [],
        });
      }
      const run = runMap.get(runKey);
      const sigType = row.signal_type || _deriveScanSignalType(row.selected_signal_type);
      const vs = row.valid_signals_count;
      if (typeof vs === "number" && vs > 0) {
        run.signals += vs;
      } else if (sigType && sigType !== "Kein Signal") {
        run.signals += 1;
      }
      if (row.order_created) run.orders_created += 1;
      run.trades_managed += (row.related_trade_count || 0);
      run.markets.push({
        symbol: row.symbol,
        signal_type: sigType,
        decision_action: row.decision_action,
        reason: row.display_reason || row.reason || row.notes || row.skip_reason,
      });
    }
    for (const run of runMap.values()) {
      run.markets.sort((a, b) => (a.symbol || "").localeCompare(b.symbol || ""));
    }
    const scanRows = [...runMap.values()];

    const filtered = scanRows.filter((run) => {
      if (envFilter && (run.environment || "").toLowerCase() !== envFilter) return false;
      if (search) {
        const haystack = [
          formatValue(run.executed_at),
          run.environment,
          ...((run.markets || []).flatMap((m) => [m.symbol, m.signal_type, m.decision_action, m.reason])),
        ].join(" ").toLowerCase();
        if (!haystack.includes(search)) return false;
      }
      return true;
    });
    const sorted = [...filtered].sort((a, b) => {
      const result = (a.executed_at || "").localeCompare(b.executed_at || "");
      return state.sortDirection === "asc" ? result : -result;
    });
    const totalPages = Math.max(1, Math.ceil(sorted.length / state.pageSize));
    const page = Math.min(state.page, totalPages);
    const pageRows = sorted.slice((page - 1) * state.pageSize, page * state.pageSize);
    const environments = journal.filter_options?.environments || [];
    return `<div class="stack">
      <section class="card">
        <div class="toolbar">
          <div>
            <h3>Journal Scans</h3>
            <p class="muted">Gesamt: ${filtered.length} Runs von ${scanRows.length}. Letztes Update: ${formatValue(journal.generated_at)}</p>
          </div>
          <div class="toolbar-actions">
            <input class="search" type="search" placeholder="Globale Textsuche" data-table="scans" data-search="1" value="${escapeHtml(state.search)}">
            <select data-table="scans" data-filter="environment">
              <option value="">Alle Umgebungen</option>
              ${environments.map((e) => `<option value="${escapeHtml(e)}" ${state.filters.environment === e ? "selected" : ""}>${escapeHtml(e)}</option>`).join("")}
            </select>
            <select data-table="scans" data-pagesize="1">${[10, 25, 50, 100].map((s) => `<option value="${s}" ${s === state.pageSize ? "selected" : ""}>${s} / Seite</option>`).join("")}</select>
            <button class="ghost" data-action="reset" data-table="scans">Filter zuruecksetzen</button>
            <button class="ghost" data-action="refresh">Neu laden</button>
          </div>
        </div>
        ${this.loading ? `<p class="muted">Journal wird geladen...</p>` : ""}
        ${this.loadError ? `<div class="warn">Journal konnte nicht geladen werden: ${escapeHtml(this.loadError)}</div>` : ""}
        ${journal.warnings?.length ? `<div class="warn">${journal.warnings.map((w) => `<div>${escapeHtml(w)}</div>`).join("")}</div>` : ""}
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th><button class="sort" data-action="sort" data-table="scans" data-key="executed_at">Zeit${state.sortKey === "executed_at" ? ` ${state.sortDirection === "asc" ? "↑" : "↓"}` : ""}</button></th>
                <th>Umgebung</th>
                <th>Signale</th>
                <th>Orders erstellt</th>
                <th>Trades gemanaged</th>
                <th></th>
              </tr>
              <tr><th></th><th></th><th></th><th></th><th></th><th></th></tr>
            </thead>
            <tbody>
              ${pageRows.length ? pageRows.map((run) => {
                const runId = `${run.executed_at}_${run.environment}`;
                const isExpanded = this._expandedScanRuns.has(runId);
                const markets = run.markets || [];
                let html = `<tr class="expandable ${isExpanded ? "expanded" : ""}" data-action="toggle-scan" data-run-id="${escapeHtml(runId)}">
                  <td>${formatValue(run.executed_at)}</td>
                  <td>${escapeHtml(run.environment ?? "-")}</td>
                  <td>${run.signals || 0}</td>
                  <td>${run.orders_created || 0}</td>
                  <td>${run.trades_managed || 0}</td>
                  <td class="expand-icon">${isExpanded ? "▼" : "▶"}</td>
                </tr>`;
                if (isExpanded) {
                  html += `<tr class="detail-row"><td colspan="6"><table class="sub-table">
                    <thead><tr>
                      <th>Markt</th><th>Signal-Art</th><th>Entscheidung</th><th>Grund</th>
                    </tr></thead>
                    <tbody>${markets.map((m) => `<tr>
                      <td>${escapeHtml(m.symbol ?? "-")}</td>
                      <td><span class="pill ${m.signal_type === "Trend" ? "info" : m.signal_type === "Gegentrend" ? "action" : "neutral"}">${escapeHtml(m.signal_type ?? "-")}</span></td>
                      <td><span class="pill ${decisionBadgeClass(m.decision_action)}">${escapeHtml(m.decision_action ?? "-")}</span></td>
                      <td class="reason-cell">${escapeHtml(m.reason ?? "-")}</td>
                    </tr>`).join("")}</tbody>
                  </table></td></tr>`;
                }
                return html;
              }).join("") : `<tr><td colspan="6" class="empty">Keine Scan-Runs gefunden.</td></tr>`}
            </tbody>
          </table>
        </div>
        <div class="pager">
          <span>Seite ${page} / ${totalPages}</span>
          <div class="pager-btns">
            <button class="ghost" data-action="page" data-table="scans" data-page="1" ${page === 1 ? "disabled" : ""}>Erste</button>
            <button class="ghost" data-action="page" data-table="scans" data-page="${Math.max(1, page - 1)}" ${page === 1 ? "disabled" : ""}>Zurueck</button>
            <button class="ghost" data-action="page" data-table="scans" data-page="${Math.min(totalPages, page + 1)}" ${page === totalPages ? "disabled" : ""}>Weiter</button>
            <button class="ghost" data-action="page" data-table="scans" data-page="${totalPages}" ${page === totalPages ? "disabled" : ""}>Letzte</button>
          </div>
        </div>
      </section>
    </div>`;
  }

  tradesTab() {
    const journal = this.effectiveJournal();
    return `<div class="stack">
      ${this.tableTab("lifecycle", LIFECYCLE_COLUMNS, journal.lifecycle_rows || [])}
      ${this.tableTab("trades", TRADE_COLUMNS, journal.trade_rows || [])}
    </div>`;
  }

  tableTab(name, columns, rows) {
    const journal = this.effectiveJournal();
    const state = this.tableState[name];
    const filteredRows = filterRows(rows, columns, state);
    const totalPages = Math.max(1, Math.ceil(filteredRows.length / state.pageSize));
    const page = Math.min(state.page, totalPages);
    const pageRows = filteredRows.slice((page - 1) * state.pageSize, (page - 1) * state.pageSize + state.pageSize);
    const options = journal.filter_options || buildFilterOptions([], [], []);
    const sectionTitle =
      name === "lifecycle"
        ? "Signal-Lifecycle"
        : name === "trades"
          ? "Journal Orders & Trades (Rohzeilen)"
          : name === "scans"
            ? "Journal Scans"
            : "Tabelle";
    const sectionHint =
      name === "lifecycle"
        ? "Eine Zeile pro signal_lifecycle_id (neue Journale). Aeltere Eintraege ohne ID erscheinen nur unten in den Rohzeilen."
        : "";
    return `<div class="stack">
      <section class="card">
        <div class="toolbar">
          <div>
            <h3>${escapeHtml(sectionTitle)}</h3>
            <p class="muted">Gesamt: ${filteredRows.length} gefilterte Zeilen von ${rows.length}. Letztes Update: ${formatValue(journal.generated_at)}${sectionHint ? ` ${escapeHtml(sectionHint)}` : ""}</p>
          </div>
          <div class="toolbar-actions">
            <input class="search" type="search" placeholder="Globale Textsuche" data-table="${name}" data-search="1" value="${escapeHtml(state.search)}">
            <select data-table="${name}" data-pagesize="1">${[25, 50, 100, 200]
              .map((size) => `<option value="${size}" ${size === state.pageSize ? "selected" : ""}>${size} / Seite</option>`)
              .join("")}</select>
            <button class="ghost" data-action="reset" data-table="${name}">Filter zuruecksetzen</button>
            <button class="ghost" data-action="refresh">Neu laden</button>
            ${name === "trades" && this._selectedTradeRows.size > 0 ? `<button class="ghost danger" data-action="delete-selected-trades">Loeschen (${this._selectedTradeRows.size})</button>` : ""}
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
                        state.sortKey === column.key ? ` ${state.sortDirection === "asc" ? "asc" : "desc"}` : ""
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
                      (row, idx) => {
                        const isTradesTable = name === "trades";
                        const isLifecycleTable = name === "lifecycle";
                        const globalIdx = (page - 1) * state.pageSize + idx;
                        const isExpanded =
                          (isTradesTable && this._expandedTradeRows.has(globalIdx)) ||
                          (isLifecycleTable && this._expandedLifecycleRows.has(globalIdx));
                        const cells = columns
                          .map((column) => {
                            if (column.key === "_select" && isTradesTable) {
                              const isSelected = this._selectedTradeRows.has(globalIdx);
                              return `<td><input type="checkbox" data-action="select-trade" data-row-index="${globalIdx}" ${isSelected ? "checked" : ""}></td>`;
                            }
                            if (column.key === "_select") return `<td></td>`;
                            if (column.key === "_expand") {
                              return isExpanded ? `<td class="expand-icon">▼</td>` : `<td class="expand-icon">▶</td>`;
                            }
                            const value = cellValue(row, column);
                            if (column.key === "pnl") return `<td>${formatPnl(value)}</td>`;
                            if (["entry_price","stop_loss","take_profit","close_price","position_size"].includes(column.key)) {
                              return `<td>${value != null ? escapeHtml(String(value)) : "-"}</td>`;
                            }
                            if (column.key.includes("timestamp")) return `<td>${formatValue(value)}</td>`;
                            if (column.key === "decision_action") return `<td><span class="pill ${decisionBadgeClass(value)}">${formatValue(value)}</span></td>`;
                            if (column.badge) return `<td><span class="pill ${badgeClass(value)}">${formatValue(value)}</span></td>`;
                            if (column.boolean) return `<td>${value ? "Ja" : "Nein"}</td>`;
                            return `<td>${formatValue(value)}</td>`;
                          })
                          .join("");
                        const expandAction =
                          isTradesTable
                            ? `data-action="toggle-trade" data-row-index="${globalIdx}"`
                            : isLifecycleTable
                              ? `data-action="toggle-lifecycle" data-row-index="${globalIdx}"`
                              : "";
                        let html = `<tr class="${isTradesTable || isLifecycleTable ? "expandable" : ""} ${isExpanded ? "expanded" : ""}" ${expandAction}>${cells}</tr>`;
                        if (isExpanded) {
                          const detail = isLifecycleTable
                            ? buildLifecycleDetail(row)
                            : buildTradeDetail(row, journal.trade_rows || []);
                          html += `<tr class="detail-row"><td colspan="${columns.length}">${detail}</td></tr>`;
                        }
                        return html;
                      }
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
      if (tab === "status") {
        this._startLivePolling();
      } else {
        this._stopLivePolling();
      }
      if ((tab === "scans" || tab === "trades") && Date.now() - this._lastJournalRefresh > 60_000) {
        this.refreshJournal();
      } else {
        this.render();
      }
      return;
    }
    if (action === "toggle-scan" && target.dataset.runId != null) {
      const id = target.dataset.runId;
      if (this._expandedScanRuns.has(id)) {
        this._expandedScanRuns.delete(id);
      } else {
        this._expandedScanRuns.add(id);
      }
      this.render();
      return;
    }
    if (action === "select-trade" && target.dataset.rowIndex != null) {
      const idx = Number(target.dataset.rowIndex);
      if (this._selectedTradeRows.has(idx)) {
        this._selectedTradeRows.delete(idx);
      } else {
        this._selectedTradeRows.add(idx);
      }
      this.render();
      return;
    }
    if (action === "delete-selected-trades") {
      this._deleteSelectedTrades();
      return;
    }
    if (action === "toggle-trade" && target.dataset.rowIndex != null) {
      const idx = Number(target.dataset.rowIndex);
      if (this._expandedTradeRows.has(idx)) {
        this._expandedTradeRows.delete(idx);
      } else {
        this._expandedTradeRows.add(idx);
      }
      this.render();
      return;
    }
    if (action === "toggle-lifecycle" && target.dataset.rowIndex != null) {
      const idx = Number(target.dataset.rowIndex);
      if (this._expandedLifecycleRows.has(idx)) {
        this._expandedLifecycleRows.delete(idx);
      } else {
        this._expandedLifecycleRows.add(idx);
      }
      this.render();
      return;
    }
    if (action === "toggle-market-group") {
      const group = target.dataset.group || target.closest("[data-group]")?.dataset.group;
      if (group) {
        this._marketGroupsExpanded[group] = !this._marketGroupsExpanded[group];
        this.render();
      }
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
      const base = { ...BASE_TABLE_STATE };
      if (table === "lifecycle") {
        base.sortKey = "sort_timestamp";
      }
      this.setTableState(table, base);
      return;
    }
    if (action === "page" && table) {
      this.setTableState(table, { page: Number(page) });
    }
  }

  async onChange(event) {
    const target = event.target;
    if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return;
    if (target.dataset.viewerEnv) {
      this._setViewerEnv(target.value);
      return;
    }
    if (target.dataset.marketAsset) {
      const selected = this._currentMarketSelection();
      const asset = target.dataset.marketAsset;
      if (target.checked) {
        selected.add(asset);
      } else {
        selected.delete(asset);
      }
      await this._updateMarketSelection(selected);
      this._schedulePersistOperatorConfig();
      return;
    }
    const entityId = target.dataset.entity;
    if (entityId) {
      const nextVal = target instanceof HTMLInputElement && target.type === "checkbox" ? target.checked : target.value;
      await this.setEntityValue(entityId, nextVal);
      if (entityId === ENTITIES.challengeId) {
        try {
          if (typeof localStorage !== "undefined") {
            if (String(nextVal ?? "").trim()) localStorage.setItem(TA_CHALLENGE_LS_KEY, String(nextVal).trim());
            else localStorage.removeItem(TA_CHALLENGE_LS_KEY);
          }
        } catch (_) {
          /* ignore */
        }
      }
      this._schedulePersistOperatorConfig();
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
    if (target.dataset.marketFilter !== undefined) {
      this._marketFilter = target.value;
      this.render();
      return;
    }
    const { table, search } = target.dataset;
    if (table && search) {
      this.setTableState(table, { search: target.value, page: 1 });
    }
  }
  render() {
    const ld = this._effectiveLiveData();
    const journal = this.effectiveJournal();
    const title = this.panelConfig?.config?.title || "Trading Agent";
    const body =
      this.currentTab === "controls"
        ? this.controlsTab()
        : this.currentTab === "status"
          ? this.statusTab()
          : this.currentTab === "scans"
            ? this.scansTab()
            : this.tradesTab();

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
      .ghost.danger { color: #b42318; border-color: #b42318; }
      .sort { background: none; color: inherit; padding: 0; font: inherit; text-align: left; }
      .tab:hover, .btn:hover, .ghost:hover { transform: translateY(-1px); }
      .stack { display: flex; flex-direction: column; gap: 16px; }
      .grid { display: grid; gap: 16px; }
      .grid.two { grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }
      .grid.cards { grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
      .card { background: rgba(255, 255, 255, 0.95); border: 1px solid #dce4ef; border-radius: 20px; padding: 18px; box-shadow: 0 16px 32px rgba(22, 33, 51, 0.06); }
      .card-narrow { max-width: 560px; width: 100%; margin-inline: auto; }
      .card h3 { margin: 0 0 14px; font-size: 18px; }
      .field, .toggle { display: flex; flex-direction: column; gap: 8px; font-size: 13px; color: #5d6b81; }
      .toggle { flex-direction: row; align-items: center; gap: 10px; color: #162133; }
      .toggle-row { display: flex; gap: 18px; margin-top: 12px; flex-wrap: wrap; }
      input, select { width: 100%; border: 1px solid #d4ddea; border-radius: 12px; padding: 10px 12px; box-sizing: border-box; background: #f9fbfd; color: #162133; }
      .button-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
      .status-list { display: flex; flex-direction: column; gap: 10px; }
      .status-row { display: flex; justify-content: space-between; gap: 16px; font-size: 14px; align-items: flex-start; }
      .label { color: #5d6b81; flex-shrink: 0; max-width: 42%; }
      .value { text-align: right; min-width: 0; max-width: 58%; word-break: break-word; overflow-wrap: anywhere; }
      .muted { color: #6a7890; margin: 0 0 12px 0; font-size: 13px; }
      .overview-table { width: 100%; border-collapse: collapse; min-width: 0; font-size: 13px; }
      .overview-table th, .overview-table td { border: 1px solid #e2e8f0; padding: 8px 10px; text-align: left; }
      .overview-table .num { text-align: right; }
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
      .pill.action { background: #d1fae5; color: #065f46; border: 1px solid #6ee7b7; }
      .pill.close { background: #fff1d6; color: #8a5a00; border: 1px solid #fcd98a; }
      .pnl-pos { color: #146c43; font-weight: 600; }
      .pnl-neg { color: #b42318; font-weight: 600; }
      .pnl-live { font-size: 20px; font-weight: 700; }
      .card-highlight { border-color: #6ee7b7; background: linear-gradient(135deg, rgba(209,250,229,0.4) 0%, rgba(255,255,255,0.95) 60%); }
      .stats-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }
      .stat-tile { background: rgba(255,255,255,0.95); border: 1px solid #dce4ef; border-radius: 16px; padding: 14px 16px; text-align: center; box-shadow: 0 8px 16px rgba(22,33,51,0.05); }
      .stat-value { font-size: 22px; font-weight: 700; color: #162133; margin-bottom: 4px; }
      .stat-label { font-size: 12px; color: #5d6b81; }
      .warn { border-radius: 16px; background: #fff1d6; color: #8a5a00; border: 1px solid #ffd28a; padding: 14px 16px; display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
      .summary { margin: 0; padding-left: 20px; }
      .pager { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-top: 14px; flex-wrap: wrap; }
      .pager-btns { display: flex; gap: 8px; flex-wrap: wrap; }
      .empty { text-align: center; color: #6a7890; padding: 24px 16px; }
      tr.expandable { cursor: pointer; }
      tr.expandable:hover { background: #f0f4f8; }
      tr.expanded { background: #f7f9fc; }
      .expand-icon { width: 28px; text-align: center; color: #5d6b81; user-select: none; }
      tr.expandable:hover .expand-icon { color: #1f7a8c; }
      .detail-row td { padding: 16px 20px; background: #fafbfd; border-left: 3px solid #1f7a8c; }
      .sub-table { width: 100%; border-collapse: collapse; font-size: 12px; }
      .sub-table th { background: #eef3f8; padding: 6px 10px; text-align: left; font-weight: 600; color: #324057; white-space: nowrap; }
      .sub-table td { padding: 6px 10px; border-bottom: 1px solid #edf1f6; vertical-align: top; }
      .sub-table tr:last-child td { border-bottom: none; }
      .reason-cell { max-width: 280px; color: #5d6b81; font-size: 12px; }
      .detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 14px; }
      .detail-label { color: #5d6b81; font-size: 12px; display: block; margin-bottom: 2px; }
      .event-log { border-top: 1px solid #edf1f6; padding-top: 12px; }
      .event-log h4 { margin: 0 0 10px; font-size: 14px; color: #324057; }
      .event-item { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; padding: 8px 0; border-bottom: 1px solid #f0f2f5; font-size: 13px; }
      .event-time { color: #5d6b81; min-width: 140px; }
      .event-note { color: #6a7890; font-style: italic; }
      .market-selector { margin-top: 8px; }
      .market-search { margin-bottom: 8px; }
      .market-group { border: 1px solid #e2e8f0; border-radius: 12px; margin-bottom: 8px; overflow: hidden; }
      .market-group-header { padding: 10px 14px; background: #f7f9fc; cursor: pointer; font-weight: 600; font-size: 13px; color: #324057; user-select: none; }
      .market-group-header:hover { background: #eef3f8; }
      .market-checkbox-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 4px 8px; padding: 10px 14px; max-height: 280px; overflow-y: auto; }
      .market-item { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #162133; cursor: pointer; padding: 3px 0; }
      .market-item input[type="checkbox"] { width: auto; margin: 0; cursor: pointer; }
      .market-item:hover { color: #1f7a8c; }
      .ws-pos-block { border-top: 1px solid #e5e9ef; margin-top: 10px; padding-top: 10px; }
      @media (max-width: 900px) {
        .page { padding: 16px; }
        .hero { flex-direction: column; }
        .search { min-width: 0; width: 100%; }
        .market-checkbox-grid { grid-template-columns: repeat(auto-fill, minmax(90px, 1fr)); }
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
          <span class="chip">PnL: ${formatPnl(ld?.account_unrealized_pnl)}</span>
          <span class="chip">Offene Positionen: ${formatValue(ld?.account_open_positions_count)}</span>
          ${ld?.account_total_margin_balance != null && ld?.account_total_margin_balance !== "" ? `<span class="chip">Gesamt Margin: ${formatCurrency(ld.account_total_margin_balance)}</span>` : ""}
          ${Number(ld?.active_challenges_count) > 1 ? `<span class="chip">Challenges: ${escapeHtml(String(ld.active_challenges_count))}</span>` : ""}
          <span class="chip">Tests: ${formatValue(this.entity(ENTITIES.tests)?.state)}</span>
          <span class="chip">Panel: ${escapeHtml(PANEL_VERSION)}</span>
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












