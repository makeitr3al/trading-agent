const PANEL_NAME = "trading-agent-admin-panel";
const JOURNAL_URL = "/local/trading-agent/journal_table.json";
const REGISTRY_URL = "/local/trading-agent/asset_registry.json";
const HOME_URL = "/lovelace";
const PANEL_VERSION = "__PANEL_VERSION__";
const CHALLENGES_URL = "/local/trading-agent/challenges.json";
const RUN_SUMMARY_URL = "/local/trading-agent/run_summary.json";
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

/** HA `trading_agent_sync_panel_assets_haos` may write a JSON placeholder with source "unknown" (HTTP 200). It must not shadow the live_status sensor. */
function isUsableLiveStatusPayload(d) {
  if (!d || typeof d !== "object") return false;
  const src = String(d.source ?? "").toLowerCase();
  if (src === "unknown") return false;
  const ovN = Array.isArray(d.challenges_overview) ? d.challenges_overview.length : 0;
  const posN = Array.isArray(d.open_positions_summary) ? d.open_positions_summary.length : 0;
  const nOpen = Number(d.account_open_positions_count ?? 0);
  const pnl = d.account_unrealized_pnl;
  const hasPnl = pnl !== null && pnl !== undefined && pnl !== "" && !Number.isNaN(Number(pnl));
  const hasMoney = [d.margin_balance, d.balance, d.available_balance, d.initial_balance].some(
    (v) => v !== null && v !== undefined && v !== "" && !Number.isNaN(Number(v)),
  );
  if (d.updated_at) return true;
  if (hasMoney || hasPnl || nOpen > 0 || ovN > 0 || posN > 0) return true;
  if (d.last_error && String(d.last_error).trim() && src === "poll") return true;
  return false;
}

function mergeNonNullLive(base, overlay) {
  if (!overlay) return base || null;
  if (!base) return { ...overlay };
  const out = { ...base };
  for (const k of Object.keys(overlay)) {
    const v = overlay[k];
    if (k === "challenges_overview" || k === "open_positions_summary") {
      if (Array.isArray(v) && v.length) out[k] = v;
      continue;
    }
    if (v === null || v === undefined || v === "") continue;
    out[k] = v;
  }
  return out;
}

function liveStatusFromEntity(entity) {
  if (!entity) return null;
  const a = entity.attributes || {};
  return {
    account_unrealized_pnl: a.account_unrealized_pnl,
    account_open_positions_count: a.account_open_positions_count,
    websocket_connected: a.websocket_connected,
    source: entity.state,
    last_error: a.last_error,
    updated_at: a.updated_at,
    environment: a.environment,
    challenge_name: a.challenge_name,
    challenge_id: a.challenge_id,
    initial_balance: a.initial_balance,
    balance: a.balance,
    margin_balance: a.margin_balance,
    available_balance: a.available_balance,
    high_water_mark: a.high_water_mark,
    open_positions_summary: a.open_positions_summary,
    challenges_overview: a.challenges_overview,
    active_challenges_count: a.active_challenges_count,
    account_total_margin_balance: a.account_total_margin_balance,
  };
}

function isUsableRunSummaryPayload(s) {
  if (!s || typeof s !== "object") return false;
  const rid = String(s.run_id ?? "").trim().toLowerCase();
  if (!rid || rid === "unknown" || rid === "unavailable") return false;
  return true;
}

function runSummaryFromEntity(entity) {
  if (!entity) return null;
  const a = entity.attributes || {};
  return {
    run_id: entity.state,
    mode: a.mode,
    environment: a.environment,
    started_at: a.started_at,
    finished_at: a.finished_at,
    success: a.success,
    exit_code: a.exit_code,
    suite: a.suite,
    entry_count: a.entry_count,
    cycle_count: a.cycle_count,
    order_count: a.order_count,
    trade_count: a.trade_count,
    symbols: a.symbols,
    latest_symbol: a.latest_symbol,
    latest_outcome: a.latest_outcome,
    title: a.title,
    notification_title: a.notification_title,
    notification_message: a.notification_message,
    summary_lines: a.summary_lines,
  };
}

function mergeNonNullRunSummary(base, overlay) {
  if (!overlay) return base || null;
  if (!base) return { ...overlay };
  const out = { ...base };
  for (const k of Object.keys(overlay)) {
    const v = overlay[k];
    if (v === null || v === undefined || v === "") continue;
    if (k === "summary_lines" && Array.isArray(v) && v.length === 0) continue;
    out[k] = v;
  }
  return out;
}

/** When Propr reports multiple active challenges, sync_live_status omits top-level balances; aggregate from challenges_overview. */
function aggregateKpiBalances(ld) {
  let balance = ld?.margin_balance ?? ld?.balance ?? null;
  let initialBalance = ld?.initial_balance ?? null;
  let marginBalance = ld?.margin_balance ?? null;
  let availableBalance = ld?.available_balance ?? null;
  const ov = Array.isArray(ld?.challenges_overview) ? ld.challenges_overview : [];
  const sumKey = (rows, key) => {
    const parts = rows.map(r => Number(r[key])).filter(n => !Number.isNaN(n));
    return parts.length ? parts.reduce((a, c) => a + c, 0) : null;
  };
  if (ov.length && (balance == null || initialBalance == null)) {
    if (balance == null) {
      const t = ld?.account_total_margin_balance;
      balance = t != null && !Number.isNaN(Number(t)) ? Number(t) : sumKey(ov, "margin_balance");
    }
    if (balance == null) balance = sumKey(ov, "balance");
    if (marginBalance == null) marginBalance = sumKey(ov, "margin_balance");
    if (availableBalance == null) availableBalance = sumKey(ov, "available_balance");
    if (initialBalance == null) initialBalance = sumKey(ov, "initial_balance");
  }
  const challengeLabel =
    ld?.challenge_name
    || (ov.length > 1 ? `${ov.length} aktive Challenges` : (ov[0]?.challenge_name || ov[0]?.challenge_id || null));
  return { balance, initialBalance, marginBalance, availableBalance, challengeLabel };
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
  triggerPollingEnabled: "input_boolean.trading_agent_trigger_polling_aktiv",
  pushEnabled: "input_boolean.trading_agent_push_aktiv",
  operatorConfig: "sensor.trading_agent_operator_config",
  liveStatus: "sensor.trading_agent_live_status",
  runSummary: "sensor.trading_agent_run_summary",
  tests: "sensor.trading_agent_tests",
  journal: "sensor.trading_agent_journal",
};

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

// ─── Utility functions ──────────────────────────────────────────────────────

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
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit",
      }).format(date);
    }
  }
  return escapeHtml(value);
}

function fmtScanTime(isoStr) {
  if (!isoStr) return "—";
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return escapeHtml(isoStr.slice(0, 19));
    const day = d.getUTCDate().toString().padStart(2, "0");
    const mon = d.toLocaleString("de-DE", { month: "short", timeZone: "UTC" });
    const hh = d.getUTCHours().toString().padStart(2, "0");
    const mm = d.getUTCMinutes().toString().padStart(2, "0");
    const ss = d.getUTCSeconds().toString().padStart(2, "0");
    return `${day} ${mon} · ${hh}:${mm}:${ss}`;
  } catch (_) { return escapeHtml(isoStr.slice(0, 19)); }
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
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(numeric);
}

function formatPnl(value) {
  if (value === null || value === undefined || value === "") return "-";
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return escapeHtml(value);
  const formatted = new Intl.NumberFormat("de-CH", {
    minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: "always",
  }).format(numeric);
  const cls = numeric > 0 ? "pos" : numeric < 0 ? "neg" : "";
  return cls ? `<span class="${cls}">${formatted}</span>` : formatted;
}

function badgeClass(value) {
  const normalized = String(value ?? "").toLowerCase();
  if (["submitted","filled","closed","success","ok","completed","true"].some(t => normalized.includes(t))) return "ok";
  if (["failed","error","invalid","not_executed"].some(t => normalized.includes(t))) return "bad";
  if (["prepared","preflight","beta_write","replaced","long","short"].some(t => normalized.includes(t))) return "info";
  return "neutral";
}

function decisionBadgeClass(value) {
  const v = String(value ?? "").toLowerCase();
  if (v.startsWith("prepare_") || v === "close_trend_and_prepare_countertrend") return "action";
  if (v === "close_trend_trade") return "close";
  if (v.startsWith("adjust_")) return "info";
  return "neutral";
}

function _deriveScanSignalType(signalType) {
  if (!signalType) return "Kein Signal";
  const upper = String(signalType).toUpperCase();
  if (upper.startsWith("TREND_")) return "Trend";
  if (upper.startsWith("COUNTERTREND_")) return "Gegentrend";
  return "Kein Signal";
}

function summarizeMarketsForStatusPanel(rawMarkets, registry) {
  const raw = String(rawMarkets ?? "").trim();
  if (!raw) return "-";
  const selected = new Set(raw.split(",").map(s => s.trim()).filter(Boolean));
  if (!selected.size) return "-";
  if (!Array.isArray(registry) || !registry.length) {
    const tickers = [...selected];
    return escapeHtml(`${tickers.length} Maerkte: ${tickers.slice(0, 4).join(", ")}${tickers.length > 4 ? "…" : ""}`);
  }
  const crypto = registry.filter(a => a.asset_type === "crypto");
  const hip3 = registry.filter(a => a.asset_type === "hip3");
  const nCrypto = crypto.filter(a => selected.has(a.name) || selected.has(a.propr_asset)).length;
  const nHip3 = hip3.filter(a => selected.has(a.name) || selected.has(a.propr_asset)).length;
  const parts = [];
  if (nCrypto) parts.push(`${nCrypto} Crypto Perps`);
  if (nHip3) parts.push(`${nHip3} Stocks & Commodities`);
  if (!parts.length) {
    const tickers = [...selected];
    return escapeHtml(`${tickers.length} Maerkte: ${tickers.slice(0, 4).join(", ")}${tickers.length > 4 ? "…" : ""}`);
  }
  return escapeHtml(`${selected.size} ausgewaehlt (${parts.join(", ")})`);
}

// ─── Data helpers ────────────────────────────────────────────────────────────

function compareValues(left, right) {
  if (left === right) return 0;
  if (left === null || left === undefined || left === "") return -1;
  if (right === null || right === undefined || right === "") return 1;
  const ln = Number(left), rn = Number(right);
  if (!Number.isNaN(ln) && !Number.isNaN(rn)) return ln < rn ? -1 : ln > rn ? 1 : 0;
  return String(left).localeCompare(String(right), "de");
}

function uniqueValues(rows, key) {
  return [...new Set(rows.map(r => r[key]).filter(v => v !== null && v !== undefined && v !== ""))]
    .sort((a, b) => String(a).localeCompare(String(b), "de"));
}

function buildFilterOptions(scanRows, tradeRows, lifecycleRows) {
  const lr = lifecycleRows || [];
  return {
    symbols: uniqueValues([...scanRows, ...tradeRows, ...lr], "symbol"),
    environments: uniqueValues([...scanRows, ...tradeRows, ...lr], "environment"),
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
    const o = row.order_status_summary || "-", t = row.trade_status_summary || "-";
    return `${o} / ${t}${row.trade_pnl_summary ? ` | PnL ${row.trade_pnl_summary}` : ""}`;
  }
  return row[column.key];
}

function filterRows(rows, columns, tableState) {
  const search = (tableState.search || "").trim().toLowerCase();
  const filtered = rows.filter(row => {
    if (search) {
      const hay = columns.map(c => String(cellValue(row, c) ?? "")).join(" ").toLowerCase();
      if (!hay.includes(search)) return false;
    }
    return columns.every(col => {
      const fv = (tableState.filters[col.key] || "").trim().toLowerCase();
      if (!fv) return true;
      const cv = String(cellValue(row, col) ?? "").toLowerCase();
      if (col.boolean) {
        if (fv === "ja") return cv === "true";
        if (fv === "nein") return cv === "false";
      }
      return col.filter === "select" ? cv === fv : cv.includes(fv);
    });
  });
  const sorted = [...filtered];
  const sortCol = columns.find(c => c.key === tableState.sortKey);
  if (sortCol) {
    sorted.sort((a, b) => {
      const r = compareValues(cellValue(a, sortCol), cellValue(b, sortCol));
      return tableState.sortDirection === "asc" ? r : -r;
    });
  }
  return sorted;
}

function buildLifecycleChains(tradeRows) {
  const byId = new Map(), ungrouped = [];
  for (const row of tradeRows) {
    if (row.lifecycle_id) {
      if (!byId.has(row.lifecycle_id)) byId.set(row.lifecycle_id, []);
      byId.get(row.lifecycle_id).push(row);
    } else { ungrouped.push(row); }
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
  for (const chain of byId.values()) lifecycles.push(chain.sort((a, b) => (a.timestamp || "").localeCompare(b.timestamp || "")));
  for (const chains of bySymbol.values()) for (const chain of chains) if (chain.length > 0) lifecycles.push(chain);
  return lifecycles;
}

function buildLifecycleDetail(row) {
  const steps = row.steps || [];
  if (!steps.length) return `<div class="da-detail-meta muted">Keine Schritte erfasst.</div>`;
  const lines = steps.map(s => {
    const kind = escapeHtml(s.step || ""), at = formatValue(s.at);
    const extra = Object.entries(s).filter(([k]) => !["step","at"].includes(k))
      .map(([k, v]) => `${escapeHtml(k)}: ${escapeHtml(v != null ? String(v) : "-")}`).join(" · ");
    return `<div class="da-event-item"><span class="da-event-time">${at}</span><span class="da-pill neutral">${kind}</span>${extra ? ` <span class="da-event-note">${extra}</span>` : ""}</div>`;
  });
  return `<div class="da-event-log"><h4 class="da-event-head">Lifecycle-Schritte</h4>${lines.join("")}</div>`;
}

function buildTradeDetail(row, allTradeRows) {
  const details = `<div class="da-detail-grid">
    <div><span class="da-detail-label">Fill-Zeit</span> ${formatValue(row.fill_timestamp)}</div>
    <div><span class="da-detail-label">Close-Zeit</span> ${formatValue(row.close_timestamp)}</div>
    <div><span class="da-detail-label">Notizen</span> ${escapeHtml(row.notes ?? "-")}</div>
  </div>`;
  const chains = buildLifecycleChains(allTradeRows);
  const chain = chains.find(c => c.some(r =>
    r.timestamp === row.timestamp && r.symbol === row.symbol && r.entry_type === row.entry_type && r.status === row.status
  )) || [];
  const related = chain.filter(r => !(r.timestamp === row.timestamp && r.entry_type === row.entry_type && r.status === row.status));
  if (!related.length) return details;
  const events = related.map(r => `<div class="da-event-item">
    <span class="da-event-time">${formatValue(r.timestamp)}</span>
    <span class="da-pill ${badgeClass(r.status)}">${escapeHtml(r.entry_type ?? "")}: ${escapeHtml(r.status ?? "")}</span>
    ${r.entry_price != null ? `<span>Entry: ${escapeHtml(String(r.entry_price))}</span>` : ""}
    ${r.stop_loss != null ? `<span>SL: ${escapeHtml(String(r.stop_loss))}</span>` : ""}
    ${r.take_profit != null ? `<span>TP: ${escapeHtml(String(r.take_profit))}</span>` : ""}
    ${r.close_price != null ? `<span>Close: ${escapeHtml(String(r.close_price))}</span>` : ""}
    ${r.pnl != null ? `<span>PnL: ${formatPnl(r.pnl)}</span>` : ""}
    ${r.notes ? `<span class="da-event-note">${escapeHtml(r.notes)}</span>` : ""}
  </div>`).join("");
  return `${details}<div class="da-event-log"><h4 class="da-event-head">Ereignis-Verlauf</h4>${events}</div>`;
}

function snapshotFallback(journalState) {
  const recentEntries = journalState?.attributes?.recent_entries || [];
  const scanRows = recentEntries.filter(e => e.entry_type === "cycle").map(e => ({
    executed_at: e.executed_at || null, timestamp: e.entry_timestamp || null,
    entry_date: e.entry_date || null, symbol: e.symbol || null, environment: e.environment || null,
    decision_action: e.decision_action || null, selected_signal_type: e.source_signal_type || null,
    signal_type: _deriveScanSignalType(e.source_signal_type), received_signals: e.source_signal_type || null,
    order_created: false, order_status_summary: null, trade_status_summary: null,
    trade_pnl_summary: e.pnl ?? null, skip_reason: e.skipped_reason || null, notes: e.notes || null,
    scan_cycle_phase: null,
    display_reason: (e.notes && e.skipped_reason) ? `${e.notes} • not executed: ${e.skipped_reason}` : (e.notes || e.skipped_reason || null),
    related_order_count: 0, related_trade_count: 0, entry_price: null, fill_time: null, tp: null, sl: null, exit_price: null, exit_time: null,
  }));
  const tradeRows = recentEntries.filter(e => e.entry_type && e.entry_type !== "cycle").map(e => ({
    timestamp: e.entry_timestamp || null, entry_type: e.entry_type || null, symbol: e.symbol || null,
    environment: e.environment || null, status: e.status || null, direction: e.direction || null,
    source_signal_type: e.source_signal_type || null, position_size: e.position_size ?? null,
    entry_price: e.entry_price ?? null, stop_loss: e.stop_loss ?? null, take_profit: e.take_profit ?? null,
    close_price: e.close_price ?? null, lifecycle_id: e.lifecycle_id ?? null, pnl: e.pnl ?? null,
    fill_timestamp: e.fill_timestamp || null, close_timestamp: e.close_timestamp || null, notes: e.notes || null,
  }));
  if (!scanRows.length && !tradeRows.length) return {
    generated_at: null, latest_entry_timestamp: null, journal_path: null, exists: false,
    entry_count_total: 0, scan_rows: [], trade_rows: [], lifecycle_rows: [],
    filter_options: buildFilterOptions([], [], []), warnings: [],
  };
  return {
    generated_at: journalState?.attributes?.latest_entry_timestamp || null,
    latest_entry_timestamp: journalState?.attributes?.latest_entry_timestamp || null,
    journal_path: journalState?.attributes?.journal_path || null,
    exists: Boolean(journalState?.attributes?.exists),
    entry_count_total: Number(journalState?.attributes?.entry_count || scanRows.length + tradeRows.length || 0),
    scan_rows: scanRows, trade_rows: tradeRows, lifecycle_rows: [],
    filter_options: buildFilterOptions(scanRows, tradeRows, []),
    warnings: ["Panel verwendet Journal-Snapshot als Fallback, weil /local/trading-agent/journal_table.json leer oder veraltet ist."],
  };
}

// ─── Scan cycle helpers ──────────────────────────────────────────────────────

function groupScansByCycle(scanRows) {
  const map = new Map();
  for (const row of scanRows) {
    const key = row.executed_at || row.timestamp || "";
    if (!map.has(key)) map.set(key, { key, time: key, env: row.environment || "", phase: row.scan_cycle_phase || "execute", rows: [] });
    map.get(key).rows.push(row);
  }
  const cycles = [...map.values()].sort((a, b) => b.key.localeCompare(a.key));
  cycles.forEach((c, i) => { c.cycleNum = cycles.length - i; });
  return cycles;
}

function cycleTrigger(rows) {
  for (const r of rows) if (/^TRIGGER/i.test(r.decision_action || "")) return "trigger-poll";
  return "schedule";
}

function cycleStats(rows) {
  let fired = 0, managed = 0, blocked = 0;
  for (const r of rows) {
    if (r.order_created) fired++;
    if (/^(MANAGE|CLOSE|ADJUST|TRIGGER)/i.test(r.decision_action || "")) managed++;
    if (/^BLOCKED/i.test(r.decision_action || "") || r.skip_reason) blocked++;
  }
  return { fired, managed, blocked };
}

// ─── SVG helpers ─────────────────────────────────────────────────────────────

function miniSparklineSvg(seed, w, h, up) {
  let s = 0;
  for (const c of String(seed)) s = (s * 31 + c.charCodeAt(0)) >>> 0;
  const pts = [];
  let v = 50;
  for (let i = 0; i < 24; i++) {
    s = (s * 1664525 + 1013904223) >>> 0;
    v += (((s >>> 16) & 0xffff) / 0xffff - 0.5) * 6 + (up ? 0.4 : -0.4);
    pts.push(v);
  }
  const min = Math.min(...pts), max = Math.max(...pts), range = max - min || 1;
  const stepX = w / (pts.length - 1);
  const toY = p => h - ((p - min) / range) * h;
  let d = `M 0 ${toY(pts[0]).toFixed(2)}`;
  pts.forEach((p, i) => { if (i > 0) d += ` L ${(i * stepX).toFixed(2)} ${toY(p).toFixed(2)}`; });
  const stroke = up ? "#22d3a7" : "#f87171";
  return `<svg width="${w}" height="${h}" style="display:block"><path d="${d}" fill="none" stroke="${stroke}" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}

function equitySparklineSvg(points, w, h) {
  if (!points || points.length < 2) return "";
  const min = Math.min(...points), max = Math.max(...points), range = max - min || 1;
  const stepX = w / (points.length - 1);
  const toY = p => h - ((p - min) / range) * h;
  let d = `M 0 ${toY(points[0]).toFixed(2)}`;
  points.forEach((p, i) => { if (i > 0) d += ` L ${(i * stepX).toFixed(2)} ${toY(p).toFixed(2)}`; });
  const isUp = points[points.length - 1] >= points[0];
  const color = isUp ? "#22d3a7" : "#f87171";
  const fill = isUp ? "rgba(34,211,167,0.10)" : "rgba(248,113,113,0.10)";
  return `<svg width="${w}" height="${h}" style="display:block;overflow:visible"><path d="${d} L ${w} ${h} L 0 ${h} Z" fill="${fill}"/><path d="${d}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}

function candleStripSvg(seed, w, h, count, up) {
  let s = 0;
  for (const c of String(seed)) s = (s * 31 + c.charCodeAt(0)) >>> 0;
  const candles = [];
  let price = 50;
  for (let i = 0; i < count; i++) {
    s = (s * 1664525 + 1013904223) >>> 0; const r1 = ((s >>> 16) & 0xffff) / 0xffff;
    s = (s * 1664525 + 1013904223) >>> 0; const r2 = ((s >>> 16) & 0xffff) / 0xffff;
    const o = price; price = price + (r1 - 0.5) * 4 + (up ? 0.25 : -0.25); const c2 = price;
    candles.push({ o, c: c2, hi: Math.max(o, c2) + r2 * 1.6, lo: Math.min(o, c2) - r2 * 1.6 });
  }
  const all = candles.flatMap(c => [c.hi, c.lo]);
  const min = Math.min(...all), max = Math.max(...all), range = max - min || 1;
  const cw = w / count, toY = v => h - ((v - min) / range) * h;
  const paths = candles.map((c, i) => {
    const x = i * cw + cw / 2, isUp2 = c.c >= c.o, col = isUp2 ? "#22d3a7" : "#f87171";
    const y1 = Math.min(toY(c.o), toY(c.c)), y2 = Math.max(toY(c.o), toY(c.c));
    return `<line x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${toY(c.hi).toFixed(1)}" y2="${toY(c.lo).toFixed(1)}" stroke="${col}" stroke-width="1"/><rect x="${(x - cw * 0.32).toFixed(1)}" y="${y1.toFixed(1)}" width="${(cw * 0.64).toFixed(1)}" height="${Math.max(1, y2 - y1).toFixed(1)}" fill="${col}"/>`;
  }).join("");
  return `<svg width="${w}" height="${h}" style="display:block">${paths}</svg>`;
}

// ─── Main Panel Class ─────────────────────────────────────────────────────────

class TradingAgentAdminPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.hassState = null;
    this.panelConfig = null;
    this.currentTab = "scans";
    this.journalPayload = { generated_at: null, latest_entry_timestamp: null, entry_count_total: 0, scan_rows: [], trade_rows: [], lifecycle_rows: [], filter_options: buildFilterOptions([], [], []), warnings: [] };
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
    this._expandedCycles = new Set();
    this._expandedMarketDetails = new Set();
    this.assetRegistry = null;
    this.challengesList = null;
    this._mktFilter = "";
    this._mktSubTab = "crypto";
    this._watchlistExpanded = true;
    this._persistOperatorTimer = null;
    this._challengeHydrateAttempted = false;
    this._onVisibilityChange = () => { if (!document.hidden && this._liveStatusInterval) this._fetchLiveStatus(); };
    this._viewerEnv = null;
    this._stateByEnv = {};
    this._dataFetchEnvAtConnect = null;
    this._hassEnvMismatchSynced = false;
    this._directRunSummary = null;
  }

  // ── Focus preservation ──────────────────────────────────────────────────────

  _captureActiveInputState() {
    try {
      const root = this.shadowRoot;
      if (!root) return null;
      const el = root.activeElement;
      if (!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)) return null;
      const key = el.dataset.entity ? `entity:${el.dataset.entity}`
        : (el.dataset.marketFilter !== undefined) ? "marketFilter"
        : (el.dataset.table && el.dataset.search) ? `tableSearch:${el.dataset.table}`
        : (el.dataset.table && el.dataset.filter) ? `tableFilter:${el.dataset.table}:${el.dataset.filter}`
        : null;
      if (!key) return null;
      return { key, selectionStart: typeof el.selectionStart === "number" ? el.selectionStart : null, selectionEnd: typeof el.selectionEnd === "number" ? el.selectionEnd : null };
    } catch (_) { return null; }
  }

  _restoreActiveInputState(state) {
    try {
      if (!state) return;
      const root = this.shadowRoot;
      if (!root) return;
      let el = null;
      if (state.key === "marketFilter") el = root.querySelector("input[data-market-filter]");
      else if (state.key.startsWith("entity:")) el = root.querySelector(`input[data-entity="${CSS.escape(state.key.slice(7))}"]`);
      else if (state.key.startsWith("tableSearch:")) el = root.querySelector(`input[data-table="${CSS.escape(state.key.slice(12))}"][data-search]`);
      else if (state.key.startsWith("tableFilter:")) {
        const [, table, ...rest] = state.key.split(":");
        el = root.querySelector(`input[data-table="${CSS.escape(table)}"][data-filter="${CSS.escape(rest.join(":"))}"]`);
      }
      if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
        el.focus({ preventScroll: true });
        if (typeof el.setSelectionRange === "function" && state.selectionStart != null) {
          const end = Math.min(state.selectionEnd, el.value.length), start = Math.min(state.selectionStart, end);
          el.setSelectionRange(start, end);
        }
      }
    } catch (_) {}
  }

  // ── Lifecycle ───────────────────────────────────────────────────────────────

  connectedCallback() {
    this.shadowRoot.addEventListener("click", e => this.onClick(e));
    this.shadowRoot.addEventListener("change", e => this.onChange(e));
    this.shadowRoot.addEventListener("input", e => this.onInput(e));
    document.addEventListener("visibilitychange", this._onVisibilityChange);
    try {
      const stored = (typeof localStorage !== "undefined" ? localStorage.getItem(TA_VIEWER_ENV_LS_KEY) : "") || "";
      if (stored.trim()) this._viewerEnv = stored.trim();
    } catch (_) {}
    this._dataFetchEnvAtConnect = this.viewerEnv();
    this._startLivePolling();
    this.refreshJournal();
    this.fetchAssetRegistry();
    this.fetchChallenges();
    this.render();
  }

  disconnectedCallback() {
    document.removeEventListener("visibilitychange", this._onVisibilityChange);
    this._stopLivePolling();
    if (this._persistOperatorTimer != null) { clearTimeout(this._persistOperatorTimer); this._persistOperatorTimer = null; }
  }

  // ── Live polling ─────────────────────────────────────────────────────────────

  _startLivePolling() {
    if (this._liveStatusInterval) return;
    this._fetchLiveStatus();
    this._fetchRunSummary();
    this._liveStatusInterval = setInterval(() => {
      if (!document.hidden) {
        this._fetchLiveStatus();
        this._fetchRunSummary();
      }
    }, 10_000);
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
      }
      else if (primaryUrl !== "/local/trading-agent/live_status.json") {
        const fallback = await fetch(`/local/trading-agent/live_status.json?ts=${Date.now()}`, { cache: "no-store" });
        if (fallback.ok) {
          this._directLiveStatus = await fallback.json();
          this.render();
        }
      }
    } catch (_) {}
    this._checkPanelVersion();
  }

  async _fetchRunSummary() {
    try {
      const resp = await fetch(`${RUN_SUMMARY_URL}?ts=${Date.now()}`, { cache: "no-store" });
      if (!resp.ok) return;
      this._directRunSummary = await resp.json();
      if (this.currentTab === "logs") this.render();
    } catch (_) {}
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
        window.location.reload();
      }
    } catch (_) {}
  }

  // ── Data ─────────────────────────────────────────────────────────────────────

  _effectiveLiveData() {
    const fromEntity = liveStatusFromEntity(this.entity(ENTITIES.liveStatus));
    const raw = this._directLiveStatus;
    const fromFile = raw && isUsableLiveStatusPayload(raw) ? raw : null;
    if (!fromFile) return fromEntity || null;
    return mergeNonNullLive(fromEntity, fromFile);
  }

  _effectiveRunSummary() {
    const fromEntity = runSummaryFromEntity(this.entity(ENTITIES.runSummary));
    const raw = this._directRunSummary;
    const fromFile = raw && isUsableRunSummaryPayload(raw) ? raw : null;
    if (!fromFile) return fromEntity || null;
    return mergeNonNullRunSummary(fromEntity, fromFile);
  }

  set hass(value) {
    this.hassState = value;
    if (!this._viewerEnv) {
      try { const stored = localStorage.getItem(TA_VIEWER_ENV_LS_KEY) || ""; this._viewerEnv = stored.trim() || null; } catch (_) {}
    }
    if (!this._viewerEnv) {
      const opEnv = value?.states?.[ENTITIES.operatorConfig]?.attributes?.environment || value?.states?.[ENTITIES.environment]?.state || "";
      this._viewerEnv = String(opEnv || "").trim() || "beta";
    }
    if (value && !this._hassEnvMismatchSynced && this._dataFetchEnvAtConnect != null && this.viewerEnv() !== this._dataFetchEnvAtConnect) {
      this._hassEnvMismatchSynced = true;
      this.refreshJournal();
      this.fetchChallenges();
      this._fetchLiveStatus();
    }
    const runId = value?.states?.[ENTITIES.runSummary]?.state;
    if (runId && !["unknown", "unavailable"].includes(runId) && runId !== this.lastRunId) {
      this.lastRunId = runId; this.refreshJournal();
    }
    if (value && !this._challengeHydrateAttempted) {
      this._challengeHydrateAttempted = true;
      try {
        const stored = localStorage.getItem(TA_CHALLENGE_LS_KEY) || "";
        const cur = String(value.states?.[ENTITIES.challengeId]?.state ?? "").trim();
        if (!cur && stored.trim()) this.setEntityValue(ENTITIES.challengeId, stored.trim()).then(() => this._schedulePersistOperatorConfig());
      } catch (_) {}
    }
    this.render();
  }

  viewerEnv() { return String(this._viewerEnv || "").trim() || "beta"; }

  _setViewerEnv(nextEnv) {
    const env = String(nextEnv || "").trim().toLowerCase();
    if (!env || env === this.viewerEnv()) return;
    const cur = this.viewerEnv();
    this._stateByEnv[cur] = { tableState: this.tableState, expandedTradeRows: this._expandedTradeRows, expandedLifecycleRows: this._expandedLifecycleRows, selectedTradeRows: this._selectedTradeRows, expandedCycles: this._expandedCycles, expandedMarketDetails: this._expandedMarketDetails, mktFilter: this._mktFilter };
    const restore = this._stateByEnv[env];
    if (restore) {
      this.tableState = restore.tableState; this._expandedTradeRows = restore.expandedTradeRows; this._expandedLifecycleRows = restore.expandedLifecycleRows;
      this._selectedTradeRows = restore.selectedTradeRows; this._expandedCycles = restore.expandedCycles; this._expandedMarketDetails = restore.expandedMarketDetails; this._mktFilter = restore.mktFilter;
    } else {
      this.tableState = { scans: { ...BASE_TABLE_STATE }, trades: { ...BASE_TABLE_STATE }, lifecycle: { ...BASE_TABLE_STATE, sortKey: "sort_timestamp" } };
      this._expandedTradeRows = new Set(); this._expandedLifecycleRows = new Set(); this._selectedTradeRows = new Set();
      this._expandedCycles = new Set(); this._expandedMarketDetails = new Set(); this._mktFilter = "";
    }
    this._viewerEnv = env;
    try { localStorage.setItem(TA_VIEWER_ENV_LS_KEY, env); } catch (_) {}
    this._directLiveStatus = null;
    this.refreshJournal(); this.fetchChallenges();
    if (this._liveStatusInterval) this._fetchLiveStatus();
    this.render();
  }

  set panel(value) { this.panelConfig = value; this.render(); }
  entity(entityId) { return this.hassState?.states?.[entityId]; }

  async callService(domain, service, data = {}) {
    if (this.hassState) await this.hassState.callService(domain, service, data);
  }

  async setEntityValue(entityId, value) {
    if (entityId.startsWith("input_select.")) return this.callService("input_select", "select_option", { entity_id: entityId, option: value });
    if (entityId.startsWith("input_number.")) return this.callService("input_number", "set_value", { entity_id: entityId, value: Number(value) });
    if (entityId.startsWith("input_text.")) return this.callService("input_text", "set_value", { entity_id: entityId, value });
    if (entityId.startsWith("input_boolean.")) return this.callService("input_boolean", value ? "turn_on" : "turn_off", { entity_id: entityId });
    if (entityId.startsWith("input_datetime.")) return this.callService("input_datetime", "set_datetime", { entity_id: entityId, time: value });
    return Promise.resolve();
  }

  async refreshJournal() {
    this.loading = true; this.loadError = null; this._lastJournalRefresh = Date.now(); this.render();
    try {
      const env = this.viewerEnv();
      const primaryUrl = envScopedUrl(JOURNAL_URL, env);
      const response = await fetch(`${primaryUrl}?ts=${Date.now()}`, { cache: "no-store" });
      if (response.ok) {
        this.journalPayload = await response.json();
      }
      else if (primaryUrl !== JOURNAL_URL) {
        const fallback = await fetch(`${JOURNAL_URL}?ts=${Date.now()}`, { cache: "no-store" });
        if (!fallback.ok) throw new Error(`HTTP ${fallback.status}`);
        this.journalPayload = { ...await fallback.json(), warnings: [`Viewer env '${env}' konnte nicht env-spezifisch geladen werden. Fallback auf legacy ${JOURNAL_URL}.`] };
      } else throw new Error(`HTTP ${response.status}`);
    } catch (error) {
      this.loadError = error instanceof Error ? error.message : String(error);
    }
    finally { this.loading = false; this.render(); }
  }

  async fetchAssetRegistry() {
    try {
      const resp = await fetch(`${REGISTRY_URL}?ts=${Date.now()}`, { cache: "no-store" });
      if (resp.ok) { this.assetRegistry = (await resp.json()).assets || []; this.render(); }
    } catch (_) {}
  }

  async fetchChallenges() {
    try {
      const env = this.viewerEnv();
      const primaryUrl = envScopedUrl(CHALLENGES_URL, env);
      const resp = await fetch(`${primaryUrl}?ts=${Date.now()}`, { cache: "no-store" });
      if (resp.ok) { this.challengesList = await resp.json(); this.render(); }
      else if (primaryUrl !== CHALLENGES_URL) {
        const fallback = await fetch(`${CHALLENGES_URL}?ts=${Date.now()}`, { cache: "no-store" });
        if (fallback.ok) { this.challengesList = await fallback.json(); this.render(); }
      }
    } catch (_) {}
  }

  _currentMarketSelection() {
    const raw = this.entity(ENTITIES.markets)?.state ?? "";
    return new Set(raw.split(",").map(s => s.trim()).filter(Boolean));
  }

  async _updateMarketSelection(selected) {
    await this.setEntityValue(ENTITIES.markets, [...selected].join(","));
  }

  _schedulePersistOperatorConfig() {
    if (this._persistOperatorTimer != null) clearTimeout(this._persistOperatorTimer);
    this._persistOperatorTimer = setTimeout(() => {
      this._persistOperatorTimer = null;
      this.callService("script", "turn_on", { entity_id: "script.trading_agent_save_current_config_haos" });
    }, PERSIST_OPERATOR_DEBOUNCE_MS);
  }

  async _deleteSelectedTrades() {
    const tradeRows = this.effectiveJournal().trade_rows || [];
    const entries = [];
    for (const idx of this._selectedTradeRows) {
      const row = tradeRows[idx];
      if (row) entries.push({ entry_timestamp: row.timestamp, symbol: row.symbol, environment: row.environment || this.viewerEnv(), entry_type: row.entry_type, status: row.status });
    }
    if (!entries.length) return;
    try {
      await this.hassState.callService("shell_command", "trading_agent_delete_journal_entries_haos", { entries: JSON.stringify(entries) });
      this._selectedTradeRows.clear(); this._expandedTradeRows.clear();
      await new Promise(r => setTimeout(r, 1000));
      await this.refreshJournal();
    } catch (err) {
      console.error("[Trading Agent] Delete failed:", err);
    }
  }

  effectiveJournal() {
    const live = this.journalPayload || {};
    if ((live.entry_count_total || 0) > 0 || (live.scan_rows?.length || 0) > 0 || (live.trade_rows?.length || 0) > 0 || (live.lifecycle_rows?.length || 0) > 0) return live;
    return snapshotFallback(this.entity(ENTITIES.journal));
  }

  setTableState(name, patch) {
    this.tableState = { ...this.tableState, [name]: { ...this.tableState[name], ...patch } };
    this.render();
  }

  challengeSelector() {
    const challenges = this.challengesList;
    const currentId = String(this.entity(ENTITIES.challengeId)?.state ?? "").trim();
    if (!challenges || !challenges.length) {
      return `<label class="dirA-field"><span>Challenge Attempt ID</span><input class="dirA-input" data-entity="${ENTITIES.challengeId}" type="text" value="${escapeHtml(currentId)}"></label>`;
    }
    const attemptIds = new Set(challenges.map(c => String(c.attempt_id || "").trim()).filter(Boolean));
    const hasAttemptMatch = currentId && attemptIds.has(currentId);
    if (currentId && !hasAttemptMatch) {
      const upgrade = challenges.find(c => String(c.challenge_id || "").trim() === currentId && String(c.attempt_id || "").trim());
      if (upgrade) this.setEntityValue(ENTITIES.challengeId, String(upgrade.attempt_id).trim()).then(() => this._schedulePersistOperatorConfig());
    }
    const effectiveId = hasAttemptMatch ? currentId : "";
    const options = [`<option value="" ${!effectiveId ? "selected" : ""}>-- Automatisch --</option>`,
      ...challenges.map(c => {
        const bal = c.initial_balance ? ` ($${Number(c.initial_balance).toLocaleString("en-US")})` : "";
        const attemptId = String(c.attempt_id || "").trim();
        return `<option value="${escapeHtml(attemptId)}" ${attemptId === effectiveId ? "selected" : ""}>${escapeHtml(c.name || c.challenge_id)}${bal}</option>`;
      })].join("");
    return `<label class="dirA-field"><span>Challenge</span><select class="dirA-input" data-entity="${ENTITIES.challengeId}">${options}</select></label>`;
  }

  // ── CSS ───────────────────────────────────────────────────────────────────

  _css() {
    return `
:host { display:block; height:100%; overflow:hidden; }
.dirA {
  --bg:#0b0e13; --bg-2:#0f1319; --bg-3:#141a22;
  --line:#1d2530; --line-2:#283242;
  --fg:#d6dde6; --fg-mute:#7d8a9b; --fg-dim:#4f5b6c;
  --accent:#22d3a7; --accent-2:#f59e0b;
  --pos:#22d3a7; --neg:#f87171; --info:#60a5fa;
  --pill-bg:#1a2230;
  font-family:ui-monospace,"JetBrains Mono","SF Mono",Menlo,monospace;
  font-size:12px; color:var(--fg); background:var(--bg);
  letter-spacing:0.01em; display:flex; flex-direction:column; height:100%; overflow:hidden;
}
.muted{color:var(--fg-mute)} .pos{color:var(--pos)} .neg{color:var(--neg)}

/* Top bar */
.dirA-top{display:flex;align-items:center;gap:20px;padding:9px 18px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#0c1117 0%,#0a0e13 100%);flex-shrink:0}
.dirA-brand{display:flex;align-items:baseline;gap:10px}
.dirA-dot{width:8px;height:8px;border-radius:50%;background:var(--accent);box-shadow:0 0 8px var(--accent);flex-shrink:0}
.dirA-brand-name{font-weight:600;color:var(--fg);letter-spacing:0.04em}
.dirA-brand-ver{font-size:10px;color:var(--fg-dim);text-transform:uppercase}
.dirA-runstate{display:flex;align-items:center;gap:14px;flex:1;overflow:hidden}
.dirA-tag{font-size:10px;padding:3px 8px;border-radius:2px;letter-spacing:0.08em;font-weight:600;white-space:nowrap}
.tag-live{background:rgba(34,211,167,0.12);color:var(--accent);border:1px solid rgba(34,211,167,0.3)}
.dirA-meta{color:var(--fg-mute);font-size:11px;white-space:nowrap}
.dirA-refresh-btn{background:transparent;border:1px solid var(--line-2);color:var(--fg-mute);padding:4px 8px;font-family:inherit;font-size:12px;cursor:pointer;border-radius:2px}
.dirA-refresh-btn:hover{border-color:var(--accent);color:var(--accent)}
.dirA-envswitch{display:flex;border:1px solid var(--line-2);border-radius:3px;overflow:hidden;flex-shrink:0}
.dirA-envbtn{background:transparent;border:0;color:var(--fg-mute);padding:5px 12px;font-family:inherit;font-size:11px;cursor:pointer;letter-spacing:0.06em;font-weight:600}
.dirA-envbtn.is-active{background:var(--accent);color:#08120e}

/* KPI strip */
.dirA-kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--line);border-bottom:1px solid var(--line);flex-shrink:0}
.dirA-kpi{background:var(--bg-2);padding:11px 14px;display:flex;flex-direction:column;gap:5px;min-height:100px}
.dirA-kpi-label{font-size:10px;color:var(--fg-mute);letter-spacing:0.12em;text-transform:uppercase}
.dirA-kpi-value{font-size:20px;font-weight:600;color:var(--fg);font-variant-numeric:tabular-nums}
.dirA-kpi-value.pos{color:var(--pos)} .dirA-kpi-value.neg{color:var(--neg)}
.dirA-kpi-sub{font-size:11px;color:var(--fg-mute)}
.dirA-kpi-sub.pos{color:var(--pos)} .dirA-kpi-sub.neg{color:var(--neg)}
.dirA-kpi-spark{margin-top:auto;opacity:0.95}
.dirA-kpi-row{display:flex;gap:12px;margin-top:auto;flex-wrap:wrap}
.dirA-kpi-cell{display:flex;flex-direction:column;gap:2px;font-size:11px}
.dirA-kpi-cell .muted{font-size:9px;letter-spacing:0.1em;text-transform:uppercase}
.dirA-kpi-mini{display:flex;gap:8px;align-items:center;font-size:11px;margin-top:auto;flex-wrap:wrap}
.dirA-statlist{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:4px;font-size:11px}
.dirA-led{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--fg-dim);margin-right:5px;vertical-align:middle;flex-shrink:0}
.dirA-led.ok{background:var(--pos);box-shadow:0 0 4px var(--pos)}
.dirA-led.warn{background:var(--accent-2);box-shadow:0 0 4px var(--accent-2)}

/* Two-pane grid */
.dirA-grid{display:grid;grid-template-columns:280px 1fr;flex:1;min-height:0;overflow:hidden}
.dirA-rail{border-right:1px solid var(--line);background:var(--bg-2);overflow-y:auto}
.dirA-section{border-bottom:1px solid var(--line);padding:12px 14px}
.dirA-section-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;cursor:pointer;user-select:none}
.dirA-section-title{font-size:10px;font-weight:700;letter-spacing:0.16em;color:var(--fg-mute)}
.dirA-section-meta{font-size:10px;color:var(--fg-dim)}
.dirA-fields{display:flex;flex-direction:column;gap:7px}
.dirA-field{display:flex;flex-direction:column;gap:3px;font-size:11px}
.dirA-field>span{color:var(--fg-mute);font-size:9px;letter-spacing:0.1em;text-transform:uppercase}
.dirA-input{background:var(--bg);border:1px solid var(--line-2);color:var(--fg);padding:5px 8px;font-family:inherit;font-size:11px;border-radius:2px;width:100%;box-sizing:border-box}
.dirA-input:focus{outline:1px solid var(--accent);border-color:var(--accent)}
.dirA-seg{display:flex;border:1px solid var(--line-2);border-radius:2px;overflow:hidden}
.dirA-seg button{background:transparent;border:0;border-right:1px solid var(--line-2);color:var(--fg-mute);padding:5px 8px;font-family:inherit;font-size:10px;flex:1;cursor:pointer;letter-spacing:0.04em}
.dirA-seg button:last-child{border-right:0}
.dirA-seg button.is-on{background:var(--accent);color:#08120e;font-weight:600}
.dirA-toggles{display:flex;flex-direction:column;gap:5px;margin-top:4px;font-size:11px;color:var(--fg)}
.dirA-toggles label{display:flex;align-items:center;gap:6px;cursor:pointer}
.dirA-actions{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-top:10px}
.dirA-btn{background:var(--bg-3);border:1px solid var(--line-2);color:var(--fg);padding:6px 10px;font-family:inherit;font-size:11px;cursor:pointer;border-radius:2px;letter-spacing:0.03em}
.dirA-btn:hover{border-color:var(--accent)}
.dirA-btn:disabled{opacity:0.4;cursor:default}
.dirA-btn:disabled:hover{border-color:var(--line-2)}
.dirA-btn.primary{background:var(--accent);color:#08120e;border-color:var(--accent);font-weight:600;grid-column:span 2}
.dirA-btn.ghost{background:transparent;border-style:dashed;color:var(--fg-mute)}
.dirA-btn.full{grid-column:span 2;width:100%}

/* Watchlist */
.dirA-mkt-list{display:flex;flex-direction:column;gap:1px}
.dirA-mkt-row{display:grid;grid-template-columns:1fr 60px auto;align-items:center;gap:6px;padding:5px 0;font-size:11px;border-bottom:1px solid var(--line)}
.dirA-mkt-row:last-of-type{border-bottom:0}
.dirA-mkt-left{display:flex;align-items:center;gap:7px}
.dirA-mkt-status{width:6px;height:6px;border-radius:50%;background:var(--fg-dim);flex-shrink:0}
.dirA-mkt-status.st-armed{background:var(--accent-2);box-shadow:0 0 5px var(--accent-2)}
.dirA-mkt-status.st-in-position{background:var(--info);box-shadow:0 0 5px var(--info)}
.dirA-mkt-sym{font-weight:500}
.dirA-mkt-right{text-align:right}
.dirA-mkt-price{font-variant-numeric:tabular-nums}
.dirA-mkt-chg{font-size:10px}

/* Main pane */
.dirA-main{display:flex;flex-direction:column;min-height:0;overflow:hidden}
.dirA-tabs{display:flex;align-items:center;border-bottom:1px solid var(--line);background:var(--bg-2);padding:0 8px;flex-shrink:0;overflow-x:auto}
.dirA-tab{background:transparent;border:0;border-bottom:2px solid transparent;color:var(--fg-mute);padding:10px 13px;font-family:inherit;font-size:12px;cursor:pointer;display:flex;align-items:center;gap:7px;letter-spacing:0.03em;white-space:nowrap;flex-shrink:0}
.dirA-tab.is-on{color:var(--fg);border-bottom-color:var(--accent)}
.dirA-tab-count{font-size:10px;background:var(--line-2);padding:1px 5px;border-radius:10px;color:var(--fg-mute)}
.dirA-tabs-spacer{flex:1}
.dirA-search{background:var(--bg);border:1px solid var(--line-2);color:var(--fg);padding:4px 9px;font-family:inherit;font-size:11px;border-radius:2px;min-width:220px;margin:5px 0}

/* Table (cycle view) */
.dirA-table-wrap{overflow:auto;flex:1}
.dirA-scan-toolbar{display:flex;gap:8px;align-items:center;padding:8px 14px;border-bottom:1px solid var(--line);background:var(--bg-2);flex-wrap:wrap}
.dirA-scan-toolbar select{background:var(--bg);border:1px solid var(--line-2);color:var(--fg);padding:4px 8px;font-family:inherit;font-size:11px;border-radius:2px}
.dirA-tableheader,.dirA-tr{display:grid;gap:10px;padding:6px 14px;align-items:center}
.dirA-tableheader.cols-cycles,.dirA-tr.cols-cycles{grid-template-columns:160px 70px 100px 130px 70px 1fr 50px}
.dirA-tableheader{background:var(--bg-2);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:2}
.dirA-th{font-size:10px;color:var(--fg-mute);letter-spacing:0.1em;text-transform:uppercase}
.dirA-th.end,.dirA-td.end{text-align:right}
.dirA-tr{border-bottom:1px solid var(--line);cursor:pointer;font-variant-numeric:tabular-nums}
.dirA-tr:hover{background:rgba(34,211,167,0.04)}
.dirA-tr.is-open{background:rgba(34,211,167,0.06)}
.dirA-td{font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dirA-tr-detail{background:var(--bg-3);border-bottom:1px solid var(--line)}
.dirA-cycle-subheader{display:grid;grid-template-columns:110px 160px 210px 1fr 80px;gap:10px;padding:6px 14px;background:var(--bg-2);border-bottom:1px solid var(--line)}
.dirA-cycle-row{display:grid;grid-template-columns:110px 160px 210px 1fr 80px;gap:10px;padding:6px 14px;align-items:center;border-bottom:1px solid var(--line);cursor:pointer;font-variant-numeric:tabular-nums;background:var(--bg-3)}
.dirA-cycle-row:hover{background:rgba(34,211,167,0.05)}
.dirA-cycle-row.is-open{background:rgba(34,211,167,0.08)}
.dirA-cycle-row .sym{font-weight:500}
.dirA-cycle-row .flex{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dirA-scan-detail{background:var(--bg);border-bottom:1px solid var(--line);padding:12px 14px}
.dirA-detail-grid{display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:12px}
.dirA-detail-card{background:var(--bg-2);border:1px solid var(--line);padding:10px 12px;border-radius:2px}
.dirA-detail-card h5{margin:0 0 6px;font-size:10px;color:var(--fg-mute);letter-spacing:0.12em;text-transform:uppercase;font-weight:600}
.dirA-detail-card pre{margin:0;font-size:11px;color:var(--fg);line-height:1.5;white-space:pre-wrap;word-break:break-word}
.dirA-bullet{list-style:none;padding:0;margin:0 0 8px;font-size:11px;line-height:1.7;color:var(--fg)}
.dirA-bullet li::before{content:"› ";color:var(--accent)}
.dirA-risk{display:flex;flex-direction:column;gap:2px;font-size:11px;color:var(--fg-mute)}
.dirA-cycle-stats{display:inline-flex;gap:8px;align-items:center}
.dirA-cycle-stats .cs{font-size:10px;padding:2px 6px;border-radius:2px;font-weight:600;letter-spacing:0.04em}
.cs-fired{background:rgba(34,211,167,0.15);color:var(--pos)}
.cs-managed{background:rgba(96,165,250,0.15);color:var(--info)}
.cs-blocked{background:rgba(245,158,11,0.15);color:var(--accent-2)}

/* Trades table */
.dirA-trades-wrap{overflow:auto;flex:1}
.da-table-toolbar{display:flex;gap:8px;align-items:center;padding:8px 14px;border-bottom:1px solid var(--line);background:var(--bg-2);flex-wrap:wrap;flex-shrink:0}
.da-table-toolbar select,.da-table-toolbar input{background:var(--bg);border:1px solid var(--line-2);color:var(--fg);padding:4px 8px;font-family:inherit;font-size:11px;border-radius:2px}
.da-table-section{margin-bottom:0}
.da-section-label{font-size:10px;font-weight:700;letter-spacing:0.14em;color:var(--fg-mute);text-transform:uppercase;padding:8px 14px;background:var(--bg-3);border-bottom:1px solid var(--line)}
table.da-table{width:100%;border-collapse:collapse;min-width:900px}
table.da-table th,table.da-table td{padding:6px 10px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left;font-size:11px;color:var(--fg)}
table.da-table thead th{position:sticky;top:0;background:var(--bg-2);z-index:2;font-size:10px;color:var(--fg-mute);letter-spacing:0.1em;text-transform:uppercase}
table.da-table tbody tr:hover{background:rgba(34,211,167,0.04);cursor:pointer}
table.da-table tbody tr.is-expanded{background:rgba(34,211,167,0.06)}
table.da-table tr.da-detail-row td{background:var(--bg-3);border-left:2px solid var(--accent);padding:10px 14px;cursor:default}
table.da-table tr.da-detail-row:hover{background:var(--bg-3)}
.da-sort-btn{background:none;border:0;color:inherit;font:inherit;cursor:pointer;padding:0;text-align:left;letter-spacing:inherit;text-transform:inherit}
.da-pager{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 14px;border-top:1px solid var(--line);background:var(--bg-2);flex-wrap:wrap;flex-shrink:0}
.da-pager-btns{display:flex;gap:5px}
.da-empty{text-align:center;color:var(--fg-mute);padding:24px 14px;font-size:11px}
.da-detail-meta{padding:6px 0;font-size:11px}
.da-detail-grid{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:10px}
.da-detail-label{color:var(--fg-mute);font-size:10px;display:block;margin-bottom:2px;letter-spacing:0.08em;text-transform:uppercase}
.da-event-log{border-top:1px solid var(--line-2);padding-top:10px;margin-top:6px}
.da-event-head{margin:0 0 8px;font-size:10px;color:var(--fg-mute);letter-spacing:0.12em;text-transform:uppercase;font-weight:600}
.da-event-item{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:5px 0;border-bottom:1px solid var(--line);font-size:11px}
.da-event-time{color:var(--fg-mute);min-width:130px}
.da-event-note{color:var(--fg-mute);font-style:italic}
.da-pill{display:inline-block;font-size:10px;padding:2px 6px;border-radius:2px;letter-spacing:0.06em;background:var(--pill-bg);color:var(--fg);font-weight:600}
.da-pill.ok{background:rgba(34,211,167,0.15);color:var(--pos)}
.da-pill.bad{background:rgba(248,113,113,0.15);color:var(--neg)}
.da-pill.info{background:rgba(96,165,250,0.15);color:var(--info)}
.da-pill.neutral{background:var(--pill-bg);color:var(--fg-mute)}
.da-pill.action{background:rgba(34,211,167,0.18);color:var(--pos)}
.da-pill.close{background:rgba(245,158,11,0.15);color:var(--accent-2)}

/* Pills */
.dirA-pill{display:inline-block;font-size:10px;padding:2px 6px;border-radius:2px;letter-spacing:0.06em;background:var(--pill-bg);color:var(--fg);font-weight:600}
.regime-bullish{background:rgba(34,211,167,0.15);color:var(--pos)}
.regime-bearish{background:rgba(248,113,113,0.15);color:var(--neg)}
.regime-neutral{background:rgba(125,138,155,0.18);color:var(--fg-mute)}
.sig-long{background:rgba(34,211,167,0.18);color:var(--pos)}
.sig-short{background:rgba(248,113,113,0.18);color:var(--neg)}
.act-prep{background:rgba(34,211,167,0.18);color:var(--pos)}
.act-mng{background:rgba(96,165,250,0.18);color:var(--info)}
.act-blk{background:rgba(245,158,11,0.18);color:var(--accent-2)}
.act-noop{background:var(--pill-bg);color:var(--fg-mute)}
.side-long{background:rgba(34,211,167,0.18);color:var(--pos)}
.side-short{background:rgba(248,113,113,0.18);color:var(--neg)}
.ok-soft{background:rgba(34,211,167,0.15);color:var(--pos)}

/* Markets tab */
.dirA-mkt-tab{padding:12px 14px;flex:1;overflow:auto}
.dirA-mkt-tab-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;gap:12px;flex-wrap:wrap}
.dirA-mkt-tab-title{font-size:12px;color:var(--fg);letter-spacing:0.03em}
.dirA-mkt-cats{display:flex;gap:4px;border-bottom:1px solid var(--line);margin-bottom:12px}
.dirA-mkt-cat{background:transparent;border:0;border-bottom:2px solid transparent;color:var(--fg-mute);padding:7px 12px;font-family:inherit;font-size:11px;cursor:pointer;letter-spacing:0.03em;display:flex;align-items:center;gap:6px;white-space:nowrap}
.dirA-mkt-cat.is-on{color:var(--fg);border-bottom-color:var(--accent)}
.dirA-mkt-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:7px}
.dirA-mkt-card{background:var(--bg-2);border:1px solid var(--line);border-radius:3px;padding:9px 11px;cursor:pointer;display:flex;flex-direction:column;gap:7px;transition:border-color 0.1s}
.dirA-mkt-card:hover{border-color:var(--line-2)}
.dirA-mkt-card.is-on{border-color:var(--accent);background:rgba(34,211,167,0.06)}
.dirA-mkt-card-top{display:flex;justify-content:space-between;align-items:flex-start}
.dirA-mkt-card-sym{font-weight:600;font-size:13px;color:var(--fg)}
.dirA-mkt-card-name{font-size:10px;color:var(--fg-mute);margin-top:2px}
.dirA-mkt-check{width:16px;height:16px;border-radius:2px;border:1px solid var(--line-2);display:flex;align-items:center;justify-content:center;font-size:10px;color:transparent;flex-shrink:0}
.dirA-mkt-check.is-on{background:var(--accent);border-color:var(--accent);color:#08120e;font-weight:700}
.dirA-mkt-card-mid{opacity:0.85}
.dirA-mkt-card-bot{display:flex;justify-content:space-between;align-items:baseline;font-size:11px;border-top:1px solid var(--line);padding-top:5px}

/* Misc */
.dirA-warn{background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.3);color:var(--accent-2);padding:8px 14px;font-size:11px;margin:0}
.dirA-loading{padding:10px 14px;font-size:11px;color:var(--fg-mute)}
.dirA-empty{text-align:center;color:var(--fg-mute);padding:24px 14px;font-size:11px}
.dirA-pager{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 14px;border-top:1px solid var(--line);background:var(--bg-2);flex-wrap:wrap;flex-shrink:0}
.dirA-pager-btns{display:flex;gap:5px}
.dirA-foot{display:flex;gap:20px;padding:7px 18px;border-top:1px solid var(--line);background:var(--bg-2);font-size:10px;color:var(--fg-dim);letter-spacing:0.05em;flex-shrink:0;flex-wrap:wrap}
.dirA-placeholder{display:flex;align-items:center;justify-content:center;flex:1;flex-direction:column;gap:12px;color:var(--fg-mute);font-size:12px}
.dirA-logs-pre{padding:14px;font-size:11px;line-height:1.7;flex:1;overflow:auto;margin:0;white-space:pre-wrap;color:var(--fg)}
@media(max-width:900px){
  .dirA-grid{grid-template-columns:1fr}
  .dirA-rail{border-right:0;border-bottom:1px solid var(--line);max-height:260px}
  .dirA-kpis{grid-template-columns:repeat(2,1fr)}
  .dirA-kpi{min-height:80px}
  .dirA-kpi-value{font-size:16px}
  .dirA-detail-grid{grid-template-columns:1fr}
  .dirA-cycle-subheader,.dirA-cycle-row{grid-template-columns:90px 130px 1fr 70px}
  .dirA-cycle-subheader>:last-child,.dirA-cycle-row>:last-child{display:none}
  .dirA-mkt-grid{grid-template-columns:repeat(auto-fill,minmax(130px,1fr))}
}
`;
  }

  // ── Render: top bar ────────────────────────────────────────────────────────

  _renderTopBar(ld, journal) {
    const version = PANEL_VERSION !== "__PANEL_VERSION__" ? PANEL_VERSION : "dev";
    const opMode = this.entity(ENTITIES.mode)?.state || "—";
    const lastScan = journal.latest_entry_timestamp ? fmtScanTime(journal.latest_entry_timestamp) : "—";
    const vEnv = this.viewerEnv();
    return `<header class="dirA-top">
      <div class="dirA-brand">
        <span class="dirA-dot"></span>
        <span class="dirA-brand-name">trading-agent</span>
        <span class="dirA-brand-ver">${escapeHtml(version)}</span>
      </div>
      <div class="dirA-runstate">
        <span class="dirA-tag tag-live">${escapeHtml(opMode.toUpperCase())} · ${escapeHtml(vEnv.toUpperCase())}</span>
        <span class="dirA-meta">letzter Scan ${escapeHtml(lastScan)}</span>
        ${this.loading ? '<span class="dirA-meta">⟳ laden…</span>' : ""}
        ${this.loadError ? `<span class="dirA-meta neg">⚠ ${escapeHtml(this.loadError.slice(0,50))}</span>` : ""}
        <button class="dirA-refresh-btn" data-action="refresh" title="Journal neu laden">↻</button>
      </div>
      <div class="dirA-envswitch">
        <button class="dirA-envbtn${vEnv === "beta" ? " is-active" : ""}" data-action="set-env" data-env="beta">BETA</button>
        <button class="dirA-envbtn${vEnv === "prod" ? " is-active" : ""}" data-action="set-env" data-env="prod">PROD</button>
      </div>
    </header>`;
  }

  // ── Render: KPI strip ──────────────────────────────────────────────────────

  _renderKpiStrip(ld, journal) {
    const agg = aggregateKpiBalances(ld || {});
    const balance = agg.balance;
    const initialBalance = agg.initialBalance;
    const marginForRow = agg.marginBalance ?? ld?.margin_balance ?? null;
    const availForRow = agg.availableBalance ?? ld?.available_balance ?? null;
    const openPnl = ld?.account_unrealized_pnl ?? null;
    const openCount = Number(ld?.account_open_positions_count ?? 0);
    const openPositions = Array.isArray(ld?.open_positions_summary) ? ld.open_positions_summary : [];
    const lifeClosed = (journal.lifecycle_rows || []).filter(r => r.phase === "closed" && r.pnl != null && r.pnl !== "");
    const closedTrades = (journal.trade_rows || []).filter(r => r.entry_type === "trade" && r.status === "closed");
    let realizedPnl; let winCount; let closedCountLabel;
    if (lifeClosed.length) {
      realizedPnl = lifeClosed.reduce((sum, r) => sum + (Number(r.pnl) || 0), 0);
      winCount = lifeClosed.filter(r => Number(r.pnl) > 0).length;
      closedCountLabel = lifeClosed.length;
    } else {
      realizedPnl = closedTrades.reduce((sum, r) => sum + (Number(r.pnl) || 0), 0);
      winCount = closedTrades.filter(r => Number(r.pnl) > 0).length;
      closedCountLabel = closedTrades.length;
    }
    const winRate = closedCountLabel ? Math.round(winCount / closedCountLabel * 100) : null;
    const fmtBal = n => n != null ? "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—";
    const balChg = (balance != null && initialBalance && initialBalance !== 0)
      ? ((balance - initialBalance) / initialBalance * 100) : null;
    const balChgStr = balChg != null ? `${balChg >= 0 ? "+" : ""}${balChg.toFixed(2)}%` : null;
    const firstPos = openPositions[0];
    const openSide = firstPos?.direction ?? null;
    const openDesc = firstPos ? `${escapeHtml(firstPos.symbol ?? "?")} ${openSide ? `<span class="dirA-pill side-${openSide.toLowerCase()}">${escapeHtml(openSide.toUpperCase())}</span>` : ""}` : (openCount > 0 ? `${openCount} Positionen` : "");
    const wsOk = ld?.websocket_connected === true || String(ld?.websocket_connected) === "true";
    const hasData = ld != null;
    const scanCount = (journal.scan_rows || []).length;
    const cycleCount = groupScansByCycle(journal.scan_rows || []).length;
    const equityPoints = (balance != null && initialBalance != null) ? [initialBalance, balance] : null;
    const openPnlNum = Number(openPnl);
    const realPnlNum = Number(realizedPnl);
    return `<section class="dirA-kpis">
      <div class="dirA-kpi">
        <div class="dirA-kpi-label">Equity</div>
        <div class="dirA-kpi-value ${balChg != null && balChg >= 0 ? "pos" : balChg != null ? "neg" : ""}">${fmtBal(balance)}</div>
        ${balChgStr ? `<div class="dirA-kpi-sub ${balChg >= 0 ? "pos" : "neg"}">${escapeHtml(balChgStr)} · Challenge</div>` : '<div class="dirA-kpi-sub">—</div>'}
        <div class="dirA-kpi-spark">${equityPoints ? equitySparklineSvg(equityPoints, 210, 36) : ""}</div>
      </div>
      <div class="dirA-kpi">
        <div class="dirA-kpi-label">Open PnL</div>
        <div class="dirA-kpi-value ${openPnl != null && openPnlNum >= 0 ? "pos" : openPnl != null ? "neg" : ""}">${formatPnl(openPnl)}</div>
        <div class="dirA-kpi-sub">${openCount > 0 ? `${openCount} offene Position${openCount > 1 ? "en" : ""}` : "Keine offene Position"}</div>
        <div class="dirA-kpi-mini">${openDesc}</div>
      </div>
      <div class="dirA-kpi">
        <div class="dirA-kpi-label">Realisiert · ${closedCountLabel} Trades</div>
        <div class="dirA-kpi-value ${realPnlNum >= 0 ? "pos" : "neg"}">${formatPnl(realizedPnl)}</div>
        ${winRate != null ? `<div class="dirA-kpi-sub">${winRate}% Trefferquote · ${winCount} Gewinner</div>` : '<div class="dirA-kpi-sub muted">—</div>'}
      </div>
      <div class="dirA-kpi">
        <div class="dirA-kpi-label">Konto</div>
        <div class="dirA-kpi-value">${fmtBal(balance)}</div>
        ${(agg.challengeLabel || ld?.challenge_name) ? `<div class="dirA-kpi-sub">${escapeHtml(String(agg.challengeLabel || ld.challenge_name).slice(0, 40))}</div>` : '<div class="dirA-kpi-sub muted">—</div>'}
        <div class="dirA-kpi-row">
          <div class="dirA-kpi-cell"><span class="muted">Verfügbar</span><span>${fmtBal(availForRow)}</span></div>
          <div class="dirA-kpi-cell"><span class="muted">Margin</span><span>${fmtBal(marginForRow)}</span></div>
        </div>
      </div>
      <div class="dirA-kpi">
        <div class="dirA-kpi-label">Verbindungen</div>
        <ul class="dirA-statlist">
          <li><span class="dirA-led ${hasData ? "ok" : ""}"></span> Propr · ${hasData ? "verbunden" : "keine Daten"}</li>
          <li><span class="dirA-led ${wsOk ? "ok" : hasData ? "warn" : ""}"></span> WebSocket · ${wsOk ? "orders" : "nicht verbunden"}</li>
          <li><span class="dirA-led ${scanCount > 0 ? "ok" : ""}"></span> Journal · ${cycleCount} Cycles</li>
          ${ld?.last_error ? `<li><span class="dirA-led warn"></span> ${escapeHtml(String(ld.last_error).slice(0, 42))}</li>` : ""}
        </ul>
      </div>
    </section>`;
  }

  // ── Render: left rail ─────────────────────────────────────────────────────

  _renderLeftRail(ld, journal) {
    return `<aside class="dirA-rail">
      ${this._renderOperatorSection()}
      ${this._renderWatchlist(ld, journal)}
    </aside>`;
  }

  _renderOperatorSection() {
    const mode = this.entity(ENTITIES.mode)?.state || "";
    const modeOpts = this.entity(ENTITIES.mode)?.attributes?.options || ["scharf", "preflight", "beta_write"];
    const opEnv = this.entity(ENTITIES.environment)?.state || "";
    const envOpts = this.entity(ENTITIES.environment)?.attributes?.options || ["beta", "prod"];
    const leverage = this.entity(ENTITIES.leverage)?.state || "";
    const schedOn = this.entity(ENTITIES.scheduleEnabled)?.state === "on";
    const triggerOn = this.entity(ENTITIES.triggerPollingEnabled)?.state === "on";
    const pushOn = this.entity(ENTITIES.pushEnabled)?.state === "on";
    const schedTime = String(this.entity(ENTITIES.scheduleTime)?.state || "").slice(0, 5);
    const modeSeg = modeOpts.map(m =>
      `<button class="${mode === m ? "is-on" : ""}" data-action="set-entity-val" data-entity="${ENTITIES.mode}" data-val="${escapeHtml(m)}">${escapeHtml(m)}</button>`
    ).join("");
    const envSeg = envOpts.map(e =>
      `<button class="${opEnv === e ? "is-on" : ""}" data-action="set-entity-val" data-entity="${ENTITIES.environment}" data-val="${escapeHtml(e)}">${escapeHtml(e)}</button>`
    ).join("");
    return `<div class="dirA-section">
      <div class="dirA-section-head" style="cursor:default">
        <span class="dirA-section-title">OPERATOR</span>
        <span class="dirA-section-meta">${escapeHtml(mode || "—")} · ${escapeHtml(opEnv || "—")}</span>
      </div>
      <div class="dirA-fields">
        <label class="dirA-field"><span>Modus</span><div class="dirA-seg">${modeSeg}</div></label>
        <label class="dirA-field"><span>Umgebung (Operator)</span><div class="dirA-seg">${envSeg}</div></label>
        <label class="dirA-field"><span>Leverage</span><input class="dirA-input" data-entity="${ENTITIES.leverage}" type="number" value="${escapeHtml(leverage)}"></label>
        ${this.challengeSelector()}
        <label class="dirA-field"><span>Schedule-Zeit (UTC)</span><input class="dirA-input" data-entity="${ENTITIES.scheduleTime}" type="time" value="${escapeHtml(schedTime)}" ${triggerOn ? "disabled" : ""}></label>
        <div class="dirA-toggles">
          <label><input type="checkbox" data-entity="${ENTITIES.scheduleEnabled}" ${schedOn ? "checked" : ""} ${triggerOn ? "disabled" : ""}> Scheduling</label>
          <label><input type="checkbox" data-entity="${ENTITIES.triggerPollingEnabled}" ${triggerOn ? "checked" : ""}> Trigger-Polling</label>
          <label><input type="checkbox" data-entity="${ENTITIES.pushEnabled}" ${pushOn ? "checked" : ""}> Push HA</label>
        </div>
      </div>
      <div class="dirA-actions">
        <button class="dirA-btn primary" data-action="script" data-script="script.trading_agent_scharf_lauf_haos">Scharf-Lauf jetzt</button>
        <button class="dirA-btn" data-action="script" data-script="script.trading_agent_preflight_test_haos">Preflight</button>
        <button class="dirA-btn" data-action="script" data-script="script.trading_agent_stop_haos">Stopp</button>
        <button class="dirA-btn" data-action="script" data-script="script.trading_agent_neustart_haos">Neustart</button>
      </div>
    </div>`;
  }

  _renderWatchlist(ld, journal) {
    const selected = this._currentMarketSelection();
    const openPositions = Array.isArray(ld?.open_positions_summary) ? ld.open_positions_summary : [];
    const openSymbols = new Set(openPositions.map(p => String(p.symbol || "").replace(/\/.*/, "").trim()));
    const cycles = groupScansByCycle(journal.scan_rows || []);
    const armedSymbols = new Set();
    for (const c of cycles.slice(0, 5)) {
      for (const r of c.rows) {
        if (/^TRIGGER/i.test(r.decision_action || "")) armedSymbols.add(String(r.symbol || "").replace(/\/.*/, "").trim());
      }
    }
    const markets = [...selected].sort().map(sym => {
      const clean = sym.replace(/\/.*/, "").replace(/^xyz:/, "");
      let status = "scanned";
      if (openSymbols.has(sym) || openSymbols.has(clean)) status = "in-position";
      else if (armedSymbols.has(sym) || armedSymbols.has(clean)) status = "armed";
      return `<div class="dirA-mkt-row">
        <div class="dirA-mkt-left"><span class="dirA-mkt-status st-${status}"></span><span class="dirA-mkt-sym">${escapeHtml(clean)}</span></div>
        <div class="dirA-mkt-mid">${miniSparklineSvg(sym, 54, 15, status !== "armed")}</div>
        <div class="dirA-mkt-right"><div class="dirA-mkt-chg muted">${escapeHtml(status)}</div></div>
      </div>`;
    }).join("");
    const isExp = this._watchlistExpanded !== false;
    return `<div class="dirA-section">
      <div class="dirA-section-head" data-action="toggle-watchlist">
        <span class="dirA-section-title">WATCHLIST · ${selected.size}</span>
        <span class="dirA-section-meta">${isExp ? "▾" : "▸"}</span>
      </div>
      ${isExp ? `<div class="dirA-mkt-list">
        ${markets || '<span class="muted" style="font-size:11px;padding:4px 0;display:block">Keine Märkte ausgewählt.</span>'}
        <button class="dirA-btn ghost full" style="margin-top:6px" data-action="go-markets">→ Märkte verwalten</button>
      </div>` : ""}
    </div>`;
  }

  // ── Render: scans tab ─────────────────────────────────────────────────────

  _renderScansTab(journal) {
    const flatScanRows = journal.scan_rows || [];
    const cycles = groupScansByCycle(flatScanRows);
    const state = this.tableState.scans;
    const search = (state.search || "").trim().toLowerCase();
    const envFilter = (state.filters.environment || "").toLowerCase();
    let filtered = cycles;
    if (envFilter) filtered = filtered.filter(c => (c.env || "").toLowerCase() === envFilter);
    if (search) filtered = filtered.filter(c => {
      const hay = [fmtScanTime(c.time), c.env, c.phase,
        ...c.rows.flatMap(r => [r.symbol, r.decision_action, r.notes, r.selected_signal_type, r.skip_reason])
      ].join(" ").toLowerCase();
      return hay.includes(search);
    });
    const totalPages = Math.max(1, Math.ceil(filtered.length / state.pageSize));
    const page = Math.min(state.page, totalPages);
    const pageItems = filtered.slice((page - 1) * state.pageSize, page * state.pageSize);
    const envOptions = journal.filter_options?.environments || [];

    const cycleRows = pageItems.map(c => {
      const stats = cycleStats(c.rows);
      const trigger = cycleTrigger(c.rows);
      const isOpen = this._expandedCycles.has(c.key);

      let html = `<div class="dirA-tr cols-cycles${isOpen ? " is-open" : ""}" data-action="toggle-cycle" data-cycle-key="${escapeHtml(c.key)}">
        <div class="dirA-td">${escapeHtml(fmtScanTime(c.time))}</div>
        <div class="dirA-td muted">c-${c.cycleNum}</div>
        <div class="dirA-td"><span class="dirA-pill ${trigger === "schedule" ? "act-mng" : "act-prep"}">${escapeHtml(trigger)}</span></div>
        <div class="dirA-td muted">${escapeHtml(c.phase || "execute")} · ${escapeHtml(c.env || "—")}</div>
        <div class="dirA-td">${c.rows.length}</div>
        <div class="dirA-td">
          <span class="dirA-cycle-stats">
            ${stats.fired > 0 ? `<span class="cs cs-fired">↑ ${stats.fired}</span>` : ""}
            ${stats.managed > 0 ? `<span class="cs cs-managed">⟳ ${stats.managed}</span>` : ""}
            ${stats.blocked > 0 ? `<span class="cs cs-blocked">⊘ ${stats.blocked}</span>` : ""}
            ${stats.fired === 0 && stats.managed === 0 && stats.blocked === 0 ? '<span class="muted">— keine Aktion</span>' : ""}
          </span>
        </div>
        <div class="dirA-td end">${isOpen ? "▾" : "▸"}</div>
      </div>`;

      if (isOpen) {
        const marketRows = c.rows.map((r, j) => {
          const detailKey = `${c.key}::${j}`;
          const isDetailOpen = this._expandedMarketDetails.has(detailKey);
          const sigType = r.selected_signal_type || "";
          const isLong = /LONG|BUY/i.test(sigType);
          const sigCls = sigType ? (isLong ? "sig-long" : "sig-short") : "";
          const act = r.decision_action || "";
          const actCls = /^PREPARE/i.test(act) ? "act-prep" : /^(MANAGE|CLOSE|ADJUST|TRIGGER)/i.test(act) ? "act-mng" : /^BLOCKED/i.test(act) ? "act-blk" : "act-noop";
          const note = String(r.display_reason || r.notes || r.skip_reason || "—").slice(0, 90);

          let mhtml = `<div class="dirA-cycle-row${isDetailOpen ? " is-open" : ""}" data-action="toggle-market-detail" data-detail-key="${escapeHtml(detailKey)}">
            <span class="dirA-td sym">${escapeHtml(r.symbol || "—")}</span>
            <span class="dirA-td">${sigType ? `<span class="dirA-pill ${sigCls}">${escapeHtml(sigType)}</span>` : '<span class="muted">—</span>'}</span>
            <span class="dirA-td"><span class="dirA-pill ${actCls}">${escapeHtml(act || "—")}</span></span>
            <span class="dirA-td flex muted">${escapeHtml(note)}</span>
            <span class="dirA-td end">${r.order_created ? '<span class="dirA-pill ok-soft">ORDER ✓</span>' : '<span class="muted">·</span>'}</span>
          </div>`;

          if (isDetailOpen) {
            const signals = r.received_signals
              ? String(r.received_signals).split(/\s*\|\s*/).map(s => s.trim()).filter(Boolean) : [];
            const hasRisk = r.entry_price != null || r.sl != null || r.tp != null;
            const detailLines = [
              `decision_action  = ${r.decision_action || "—"}`,
              `signal_type      = ${r.signal_type || _deriveScanSignalType(r.selected_signal_type)}`,
              `scan_phase       = ${r.scan_cycle_phase || "—"}`,
              `order_created    = ${r.order_created ? "true" : "false"}`,
              r.skip_reason ? `skip_reason      = ${r.skip_reason}` : null,
              r.notes ? `notes            = ${r.notes}` : null,
            ].filter(Boolean).join("\n");
            mhtml += `<div class="dirA-scan-detail">
              <div class="dirA-detail-grid">
                <div class="dirA-detail-card">
                  <h5>Strategie-Entscheidung · ${escapeHtml(r.symbol || "")}</h5>
                  <pre>${escapeHtml(detailLines)}</pre>
                </div>
                <div class="dirA-detail-card">
                  <h5>Signale</h5>
                  ${signals.length ? `<ul class="dirA-bullet">${signals.map(s => `<li>${escapeHtml(s)}</li>`).join("")}</ul>` : '<p class="muted" style="font-size:11px;margin:0 0 8px">Keine Signal-Details verfügbar.</p>'}
                  ${hasRisk ? `<h5>Risk Preview</h5><div class="dirA-risk">
                    ${r.entry_price != null ? `<span>Entry: ${escapeHtml(String(r.entry_price))}</span>` : ""}
                    ${r.sl != null ? `<span>SL: ${escapeHtml(String(r.sl))}</span>` : ""}
                    ${r.tp != null ? `<span>TP: ${escapeHtml(String(r.tp))}</span>` : ""}
                  </div>` : ""}
                </div>
                <div class="dirA-detail-card">
                  <h5>Chart · 1d (dekorativ)</h5>
                  ${candleStripSvg(r.symbol || "x", 260, 76, 32, !/bear/i.test(String(r.decision_action || r.notes || "")))}
                </div>
              </div>
            </div>`;
          }
          return mhtml;
        }).join("");

        html += `<div class="dirA-tr-detail">
          <div class="dirA-cycle-subheader">
            <span class="dirA-th">Markt</span>
            <span class="dirA-th">Signal</span>
            <span class="dirA-th">Entscheidung</span>
            <span class="dirA-th">Begründung</span>
            <span class="dirA-th end">Order</span>
          </div>
          ${marketRows || '<div class="dirA-empty">Keine Märkte in diesem Cycle.</div>'}
        </div>`;
      }
      return html;
    }).join("");

    return `<div class="dirA-table-wrap">
      <div class="dirA-scan-toolbar">
        <input class="dirA-search" type="search" placeholder="Suche · btc, PREPARE, blocked…" data-table="scans" data-search="1" value="${escapeHtml(state.search)}">
        <select data-table="scans" data-filter="environment">
          <option value="">Alle Umgebungen</option>
          ${envOptions.map(e => `<option value="${escapeHtml(e)}" ${state.filters.environment === e ? "selected" : ""}>${escapeHtml(e)}</option>`).join("")}
        </select>
        <select data-table="scans" data-pagesize="1">${[10, 25, 50, 100].map(s => `<option value="${s}" ${s === state.pageSize ? "selected" : ""}>${s} / Seite</option>`).join("")}</select>
        <button class="dirA-btn ghost" data-action="reset" data-table="scans">↺ Filter</button>
        <button class="dirA-btn ghost" data-action="refresh">↻ Neu laden</button>
      </div>
      ${(journal.warnings || []).length ? `<div class="dirA-warn">${journal.warnings.map(w => escapeHtml(w)).join("<br>")}</div>` : ""}
      <div class="dirA-tableheader cols-cycles">
        <div class="dirA-th">Zeit</div>
        <div class="dirA-th">Cycle</div>
        <div class="dirA-th">Trigger</div>
        <div class="dirA-th">Phase / Env</div>
        <div class="dirA-th">Märkte</div>
        <div class="dirA-th">Ergebnis</div>
        <div class="dirA-th end">Details</div>
      </div>
      ${cycleRows || `<div class="dirA-empty">${this.loading ? "Journal wird geladen…" : "Keine Scan-Cycles gefunden."}</div>`}
      <div class="dirA-pager">
        <span class="muted">Seite ${page} / ${totalPages} · ${filtered.length} Cycles von ${cycles.length}</span>
        <div class="dirA-pager-btns">
          <button class="dirA-btn ghost" data-action="page" data-table="scans" data-page="1" ${page === 1 ? "disabled" : ""}>«</button>
          <button class="dirA-btn ghost" data-action="page" data-table="scans" data-page="${Math.max(1, page - 1)}" ${page === 1 ? "disabled" : ""}>‹</button>
          <button class="dirA-btn ghost" data-action="page" data-table="scans" data-page="${Math.min(totalPages, page + 1)}" ${page === totalPages ? "disabled" : ""}>›</button>
          <button class="dirA-btn ghost" data-action="page" data-table="scans" data-page="${totalPages}" ${page === totalPages ? "disabled" : ""}>»</button>
        </div>
      </div>
    </div>`;
  }

  // ── Render: trades tab ────────────────────────────────────────────────────

  _renderTradesTab(journal) {
    const lifecycleRows = journal.lifecycle_rows || [];
    const tradeRows = journal.trade_rows || [];
    const selectedCount = this._selectedTradeRows.size;
    const lcState = this.tableState.lifecycle;
    return `<div class="dirA-trades-wrap">
      <div class="da-table-toolbar">
        <input class="dirA-search" type="search" placeholder="Suche · Markt, Status…" data-table="lifecycle" data-search="1" value="${escapeHtml(lcState.search)}">
        <select data-table="lifecycle" data-pagesize="1">${[10, 25, 50, 100].map(s => `<option value="${s}" ${s === lcState.pageSize ? "selected" : ""}>${s} / Seite</option>`).join("")}</select>
        <button class="dirA-btn ghost" data-action="reset" data-table="lifecycle">↺ Lifecycle</button>
        <button class="dirA-btn ghost" data-action="reset" data-table="trades">↺ Einträge</button>
        ${selectedCount > 0 ? `<button class="dirA-btn ghost" style="color:var(--neg);border-color:rgba(248,113,113,0.4)" data-action="delete-selected-trades">✕ ${selectedCount} löschen</button>` : ""}
      </div>
      ${lifecycleRows.length > 0 ? `<div class="da-section-label">LIFECYCLE-ÜBERSICHT · ${lifecycleRows.length}</div>${this._renderTableSection("lifecycle", LIFECYCLE_COLUMNS, lifecycleRows, journal)}` : ""}
      ${tradeRows.length > 0 ? `<div class="da-section-label">EINZEL-EINTRÄGE · ${tradeRows.length}</div>${this._renderTableSection("trades", TRADE_COLUMNS, tradeRows, journal)}` : ""}
      ${lifecycleRows.length === 0 && tradeRows.length === 0 ? `<div class="da-empty">${this.loading ? "Journal wird geladen…" : "Keine Trade-Einträge gefunden."}</div>` : ""}
    </div>`;
  }

  _renderTableSection(name, columns, rows, journal) {
    const state = this.tableState[name] || { ...BASE_TABLE_STATE };
    const tagged = rows.map((row, i) => ({ ...row, _origIdx: i }));
    const filteredRows = filterRows(tagged, columns, state);
    const totalPages = Math.max(1, Math.ceil(filteredRows.length / state.pageSize));
    const page = Math.min(state.page, totalPages);
    const pageItems = filteredRows.slice((page - 1) * state.pageSize, page * state.pageSize);
    const filterOpts = journal.filter_options || {};

    const headerCells = columns.map(col => {
      if (col.key === "_expand" || col.key === "_select") return `<th style="width:28px"></th>`;
      if (col.sortable) {
        const arrow = state.sortKey === col.key ? (state.sortDirection === "asc" ? " ↑" : " ↓") : "";
        return `<th><button class="da-sort-btn" data-action="sort" data-table="${name}" data-sort-key="${escapeHtml(col.key)}">${escapeHtml(col.label)}${arrow}</button></th>`;
      }
      return `<th>${escapeHtml(col.label)}</th>`;
    }).join("");

    const filterCells = columns.map(col => {
      if (col.key === "_expand" || col.key === "_select") return `<th></th>`;
      if (col.filter === "select") {
        const opts = filterOpts[col.optionKey] || [];
        const cur = (state.filters[col.key] || "").toLowerCase();
        const options = [`<option value="">—</option>`,
          ...opts.map(o => `<option value="${escapeHtml(String(o).toLowerCase())}" ${String(o).toLowerCase() === cur ? "selected" : ""}>${escapeHtml(o)}</option>`)
        ].join("");
        return `<th><select data-table="${name}" data-filter="${col.key}" style="width:100%;background:var(--bg);border:1px solid var(--line-2);color:var(--fg);padding:2px 4px;font-family:inherit;font-size:10px;border-radius:2px">${options}</select></th>`;
      }
      if (col.filter === "text") {
        const cur = state.filters[col.key] || "";
        return `<th><input type="search" data-table="${name}" data-filter="${col.key}" value="${escapeHtml(cur)}" placeholder="…" style="width:100%;background:var(--bg);border:1px solid var(--line-2);color:var(--fg);padding:2px 4px;font-family:inherit;font-size:10px;border-radius:2px"></th>`;
      }
      return `<th></th>`;
    }).join("");

    const bodyRows = pageItems.map(row => {
      const origIdx = row._origIdx;
      const isExpanded = name === "lifecycle" ? this._expandedLifecycleRows.has(origIdx) : this._expandedTradeRows.has(origIdx);
      const isSelected = this._selectedTradeRows.has(origIdx);
      const rowAction = name === "lifecycle" ? "toggle-lifecycle" : "toggle-trade";
      const cells = columns.map(col => {
        if (col.key === "_expand") return `<td><button class="da-sort-btn" style="padding:0 4px" data-action="${rowAction}" data-idx="${origIdx}">${isExpanded ? "▾" : "▸"}</button></td>`;
        if (col.key === "_select") return `<td><input type="checkbox" data-action="select-trade" data-idx="${origIdx}" ${isSelected ? "checked" : ""} style="cursor:pointer"></td>`;
        const v = cellValue(row, col);
        if (col.key === "pnl" || col.key === "trade_pnl_summary") return `<td>${formatPnl(v)}</td>`;
        if (col.badge) return `<td><span class="da-pill ${badgeClass(v)}">${escapeHtml(String(v ?? "—"))}</span></td>`;
        return `<td>${formatValue(v)}</td>`;
      }).join("");
      let html = `<tr class="${isExpanded ? "is-expanded" : ""}" data-action="${rowAction}" data-idx="${origIdx}">${cells}</tr>`;
      if (isExpanded) {
        const detail = name === "lifecycle" ? buildLifecycleDetail(row) : buildTradeDetail(row, journal.trade_rows || []);
        html += `<tr class="da-detail-row"><td colspan="${columns.length}">${detail}</td></tr>`;
      }
      return html;
    }).join("");

    const emptyMsg = filteredRows.length === 0 && rows.length > 0 ? "Kein Ergebnis für aktive Filter." : (this.loading ? "Wird geladen…" : "Keine Einträge.");
    return `<div class="da-table-section">
      <div style="overflow-x:auto">
        <table class="da-table">
          <thead><tr>${headerCells}</tr><tr>${filterCells}</tr></thead>
          <tbody>${bodyRows || `<tr><td colspan="${columns.length}" class="da-empty">${emptyMsg}</td></tr>`}</tbody>
        </table>
      </div>
      <div class="da-pager">
        <span class="muted">Seite ${page} / ${totalPages} · ${filteredRows.length} von ${rows.length}</span>
        <div class="da-pager-btns">
          <button class="dirA-btn ghost" data-action="page" data-table="${name}" data-page="1" ${page === 1 ? "disabled" : ""}>«</button>
          <button class="dirA-btn ghost" data-action="page" data-table="${name}" data-page="${Math.max(1, page - 1)}" ${page === 1 ? "disabled" : ""}>‹</button>
          <button class="dirA-btn ghost" data-action="page" data-table="${name}" data-page="${Math.min(totalPages, page + 1)}" ${page === totalPages ? "disabled" : ""}>›</button>
          <button class="dirA-btn ghost" data-action="page" data-table="${name}" data-page="${totalPages}" ${page === totalPages ? "disabled" : ""}>»</button>
        </div>
      </div>
    </div>`;
  }

  // ── Render: markets tab ───────────────────────────────────────────────────

  _renderMarketsTab() {
    const registry = this.assetRegistry || [];
    const selected = this._currentMarketSelection();
    const filter = (this._mktFilter || "").toLowerCase();
    const subTab = this._mktSubTab || "crypto";
    const categories = [
      { id: "crypto", label: "Crypto Perps", types: ["crypto"] },
      { id: "fx", label: "FX Perps", types: ["builder_perp"] },
      { id: "stocks", label: "Stocks & Commodities", types: ["hip3"] },
    ];
    const activeCat = categories.find(c => c.id === subTab);
    const catAssets = activeCat ? registry.filter(a => activeCat.types.includes(a.asset_type)) : [];
    const filtered = catAssets.filter(a => {
      if (!filter) return true;
      const hay = [a.name ?? "", a.sym ?? "", a.propr_asset ?? "", a.symbol ?? "", a.description ?? "", a.full_name ?? ""].join(" ").toLowerCase();
      return hay.includes(filter);
    });
    const catTabs = categories.map(cat => {
      const count = registry.filter(a => cat.types.includes(a.asset_type)).length;
      return `<button class="dirA-mkt-cat${subTab === cat.id ? " is-on" : ""}" data-action="mkt-subtab" data-subtab="${cat.id}">${escapeHtml(cat.label)} <span class="dirA-tab-count">${count}</span></button>`;
    }).join("");
    const cards = filtered.map(a => {
      const sym = a.propr_asset || a.name || "";
      const displaySym = String(sym).replace(/^xyz:/, "").toUpperCase();
      const displayName = a.description || a.full_name || a.name || displaySym;
      const isOn = selected.has(sym);
      const seedNum = [...sym].reduce((s, c) => s + c.charCodeAt(0), 0);
      const up = seedNum % 2 === 0;
      return `<div class="dirA-mkt-card${isOn ? " is-on" : ""}" data-action="toggle-market-card" data-mkt-sym="${escapeHtml(sym)}">
        <div class="dirA-mkt-card-top">
          <div>
            <div class="dirA-mkt-card-sym">${escapeHtml(displaySym)}</div>
            <div class="dirA-mkt-card-name">${escapeHtml(String(displayName).slice(0, 28))}</div>
          </div>
          <div class="dirA-mkt-check${isOn ? " is-on" : ""}">${isOn ? "✓" : ""}</div>
        </div>
        <div class="dirA-mkt-card-mid">${miniSparklineSvg(sym + "2", 120, 26, up)}</div>
        <div class="dirA-mkt-card-bot">
          <span class="muted">${escapeHtml(a.asset_type || "—")}</span>
          ${isOn ? '<span class="pos" style="font-size:10px">● aktiv</span>' : '<span class="muted" style="font-size:10px">○ inaktiv</span>'}
        </div>
      </div>`;
    }).join("");
    return `<div class="dirA-mkt-tab">
      <div class="dirA-mkt-tab-head">
        <span class="dirA-mkt-tab-title">Märkte · <strong>${selected.size}</strong> ausgewählt</span>
        <input class="dirA-search" type="search" placeholder="Suche…" data-market-filter="1" value="${escapeHtml(this._mktFilter || "")}" style="min-width:160px;margin:0">
      </div>
      <div class="dirA-mkt-cats">${catTabs}</div>
      ${registry.length === 0
        ? `<div class="dirA-empty">Asset-Registry wird geladen… (${escapeHtml(REGISTRY_URL)})</div>`
        : filtered.length > 0
          ? `<div class="dirA-mkt-grid">${cards}</div>`
          : `<div class="dirA-empty">Keine Märkte für diese Kategorie / Suche.</div>`}
    </div>`;
  }

  // ── Render: backtest + logs ───────────────────────────────────────────────

  _renderBacktestTab() {
    return `<div class="dirA-placeholder">
      <span style="font-size:28px;opacity:0.25">▦</span>
      <span>Backtest-Ergebnisse werden hier angezeigt,<br>sobald die Exportfunktion verfügbar ist.</span>
      <button class="dirA-btn ghost" disabled style="margin-top:4px">+ Neuer Run</button>
    </div>`;
  }

  _renderLogsTab() {
    const rs = this._effectiveRunSummary();
    if (rs && typeof rs === "object") {
      return `<pre class="dirA-logs-pre">${escapeHtml(JSON.stringify(rs, null, 2))}</pre>`;
    }
    return `<div class="dirA-placeholder"><span class="muted">Kein Run-Summary (${escapeHtml(RUN_SUMMARY_URL)} und ${escapeHtml(ENTITIES.runSummary)} leer).</span></div>`;
  }

  // ── Main render ────────────────────────────────────────────────────────────

  render() {
    const ais = this._captureActiveInputState();
    const ld = this._effectiveLiveData();
    const journal = this.effectiveJournal();
    const cycleCount = groupScansByCycle(journal.scan_rows || []).length;
    const tradeCount = (journal.trade_rows || []).length;
    const regCount = (this.assetRegistry || []).length;
    const tabs = [
      { id: "scans", label: "Scans", count: cycleCount },
      { id: "trades", label: "Orders & Trades", count: tradeCount },
      { id: "markets", label: "Märkte", count: regCount || null },
      { id: "backtests", label: "Backtests", count: null },
      { id: "logs", label: "Logs", count: null },
    ];
    const tabBtns = tabs.map(t => {
      const countHtml = t.count != null ? ` <span class="dirA-tab-count">${t.count}</span>` : "";
      return `<button class="dirA-tab${this.currentTab === t.id ? " is-on" : ""}" data-action="main-tab" data-tab="${t.id}">${escapeHtml(t.label)}${countHtml}</button>`;
    }).join("");
    let tabContent = "";
    if (this.currentTab === "scans") tabContent = this._renderScansTab(journal);
    else if (this.currentTab === "trades") tabContent = this._renderTradesTab(journal);
    else if (this.currentTab === "markets") tabContent = this._renderMarketsTab();
    else if (this.currentTab === "backtests") tabContent = this._renderBacktestTab();
    else tabContent = this._renderLogsTab();
    const journalPath = journal.journal_path ? String(journal.journal_path).split(/[/\\]/).pop() : "—";
    const lastSync = journal.generated_at ? fmtScanTime(journal.generated_at) : "—";
    this.shadowRoot.innerHTML = `<style>${this._css()}</style><div class="dirA">
      ${this._renderTopBar(ld, journal)}
      ${this._renderKpiStrip(ld, journal)}
      <div class="dirA-grid">
        ${this._renderLeftRail(ld, journal)}
        <div class="dirA-main">
          <div class="dirA-tabs">${tabBtns}<span class="dirA-tabs-spacer"></span></div>
          ${tabContent}
        </div>
      </div>
      <footer class="dirA-foot">
        <span>Journal: ${escapeHtml(journalPath)}</span>
        <span>${cycleCount} Cycles · ${tradeCount} Trades</span>
        <span>Sync: ${escapeHtml(lastSync)}</span>
      </footer>
    </div>`;
    this._restoreActiveInputState(ais);
  }

  // ── Event handlers ─────────────────────────────────────────────────────────

  onClick(event) {
    const el = event.target.closest("[data-action]");
    if (!el) return;
    const action = el.dataset.action;
    if (action === "main-tab") {
      this.currentTab = el.dataset.tab || "scans";
      if (this.currentTab === "logs") this._fetchRunSummary();
      this.render();
    } else if (action === "toggle-cycle") {
      const key = el.dataset.cycleKey;
      if (!key) return;
      if (this._expandedCycles.has(key)) this._expandedCycles.delete(key);
      else this._expandedCycles.add(key);
      this.render();
    } else if (action === "toggle-market-detail") {
      const key = el.dataset.detailKey;
      if (!key) return;
      if (this._expandedMarketDetails.has(key)) this._expandedMarketDetails.delete(key);
      else this._expandedMarketDetails.add(key);
      this.render();
    } else if (action === "mkt-subtab") {
      this._mktSubTab = el.dataset.subtab || "crypto";
      this._mktFilter = "";
      this.render();
    } else if (action === "toggle-watchlist") {
      this._watchlistExpanded = !this._watchlistExpanded;
      this.render();
    } else if (action === "go-markets") {
      this.currentTab = "markets";
      this.render();
    } else if (action === "set-env") {
      this._setViewerEnv(el.dataset.env);
    } else if (action === "set-entity-val") {
      const entity = el.dataset.entity, val = el.dataset.val;
      if (entity && val !== undefined) {
        this.setEntityValue(entity, val).then(() => { this._schedulePersistOperatorConfig(); this.render(); });
      }
    } else if (action === "toggle-market-card") {
      const sym = el.dataset.mktSym;
      if (!sym) return;
      const sel = this._currentMarketSelection();
      if (sel.has(sym)) sel.delete(sym); else sel.add(sym);
      this._updateMarketSelection(sel).then(() => this.render());
    } else if (action === "script") {
      const script = el.dataset.script;
      if (script) this.callService("script", "turn_on", { entity_id: script });
    } else if (action === "refresh") {
      this.refreshJournal();
    } else if (action === "reset") {
      const name = el.dataset.table;
      if (name === "lifecycle") this.setTableState(name, { ...BASE_TABLE_STATE, sortKey: "sort_timestamp" });
      else if (name) this.setTableState(name, { ...BASE_TABLE_STATE });
    } else if (action === "page") {
      const name = el.dataset.table, pg = Number(el.dataset.page);
      if (name && pg) this.setTableState(name, { page: pg });
    } else if (action === "sort") {
      const name = el.dataset.table, key = el.dataset.sortKey;
      if (name && key) {
        const cur = this.tableState[name] || BASE_TABLE_STATE;
        this.setTableState(name, { sortKey: key, sortDirection: cur.sortKey === key && cur.sortDirection === "desc" ? "asc" : "desc", page: 1 });
      }
    } else if (action === "toggle-trade") {
      const idx = Number(el.dataset.idx);
      if (!isNaN(idx)) {
        if (this._expandedTradeRows.has(idx)) this._expandedTradeRows.delete(idx);
        else this._expandedTradeRows.add(idx);
        this.render();
      }
    } else if (action === "toggle-lifecycle") {
      const idx = Number(el.dataset.idx);
      if (!isNaN(idx)) {
        if (this._expandedLifecycleRows.has(idx)) this._expandedLifecycleRows.delete(idx);
        else this._expandedLifecycleRows.add(idx);
        this.render();
      }
    } else if (action === "select-trade") {
      event.stopPropagation();
      const idx = Number(el.dataset.idx);
      if (!isNaN(idx)) {
        if (this._selectedTradeRows.has(idx)) this._selectedTradeRows.delete(idx);
        else this._selectedTradeRows.add(idx);
        this.render();
      }
    } else if (action === "delete-selected-trades") {
      this._deleteSelectedTrades();
    }
  }

  async onChange(event) {
    const el = event.target;
    const entity = el.dataset?.entity;
    if (entity) {
      const value = el.type === "checkbox" ? el.checked : el.value;
      await this.setEntityValue(entity, value);
      this._schedulePersistOperatorConfig();
      this.render();
      return;
    }
    const table = el.dataset?.table;
    if (table) {
      if (el.dataset.filter !== undefined) {
        this.setTableState(table, { filters: { ...(this.tableState[table]?.filters || {}), [el.dataset.filter]: el.value }, page: 1 });
      } else if (el.dataset.pagesize !== undefined) {
        this.setTableState(table, { pageSize: Number(el.value), page: 1 });
      }
    }
  }

  onInput(event) {
    const el = event.target;
    if (el.dataset.marketFilter !== undefined) {
      this._mktFilter = el.value;
      this.render();
      return;
    }
    const table = el.dataset?.table;
    if (table) {
      if (el.dataset.search !== undefined) {
        this.setTableState(table, { search: el.value, page: 1 });
      } else if (el.dataset.filter !== undefined) {
        this.setTableState(table, { filters: { ...(this.tableState[table]?.filters || {}), [el.dataset.filter]: el.value }, page: 1 });
      }
    }
  }
}

if (!customElements.get(PANEL_NAME)) {
  customElements.define(PANEL_NAME, TradingAgentAdminPanel);
}
