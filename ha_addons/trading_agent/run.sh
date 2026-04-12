#!/usr/bin/with-contenv bashio
set -euo pipefail

bool_to_yes_no() {
    local key="$1"
    if bashio::config.true "$key"; then
        printf 'YES'
    else
        printf 'NO'
    fi
}

# Prefix each line of merged stdout/stderr with UTC ISO8601 for Home Assistant add-on logs.
# Run in a subshell with set +e so a failing pipeline does not skip the final exit code; then
# exit with PIPESTATUS[0] (the wrapped command), not the pipeline's aggregate status.
log_cmd_lines() (
    set +e
    set -o pipefail
    "$@" 2>&1 | while IFS= read -r line || [[ -n "${line}" ]]; do
        printf '%s %s\n' "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "${line}"
    done
    exit "${PIPESTATUS[0]:-1}"
)

APP_PATH="/opt/trading-agent"
DATA_PATH="$(bashio::config 'data_path')"
VIRTUAL_ENV="/opt/venv"
OPERATOR_CONFIG_PATH="$DATA_PATH/operator_config.json"

if [[ ! -d "$APP_PATH" ]]; then
    bashio::log.fatal "Bundled app path does not exist: $APP_PATH"
    exit 1
fi

if [[ ! -x "$VIRTUAL_ENV/bin/python" ]]; then
    bashio::log.fatal "Addon virtualenv is missing: $VIRTUAL_ENV"
    exit 1
fi

mkdir -p "$DATA_PATH"
cd "$APP_PATH"

export PATH="$VIRTUAL_ENV/bin:$PATH"
export PYTHONUNBUFFERED=1
export PYTHONPATH="$APP_PATH"
export TRADING_AGENT_DATA_PATH="$DATA_PATH"
export TRADING_AGENT_OPERATOR_CONFIG_PATH="$OPERATOR_CONFIG_PATH"

# Merge stderr into the capture for debuggability on failure, but only eval lines that are
# shell exports so log warnings (e.g. legacy market format) cannot be executed as commands.
operator_env_raw="$($VIRTUAL_ENV/bin/python operator_config.py export-env --path "$OPERATOR_CONFIG_PATH" 2>&1)" || {
    bashio::log.fatal "Failed to resolve operator config"
    bashio::log.fatal "$operator_env_raw"
    exit 1
}

if printf '%s\n' "$operator_env_raw" | grep -q '^{"status": "error"'; then
    bashio::log.fatal "Operator config export returned an error payload"
    bashio::log.fatal "$operator_env_raw"
    exit 1
fi

operator_env_output="$(printf '%s\n' "$operator_env_raw" | grep '^export ' || true)"
eval "$operator_env_output"

export PROPR_ENV="$OPERATOR_ENVIRONMENT"
export PROPR_CHALLENGE_ID="$OPERATOR_CHALLENGE_ID"
export PROPR_BETA_API_KEY="$(bashio::config 'propr_beta_api_key')"
export PROPR_PROD_API_KEY="$(bashio::config 'propr_prod_api_key')"
export PROPR_PROD_CONFIRM="$(bool_to_yes_no 'propr_prod_confirm')"
export PROPR_SYMBOL="$OPERATOR_PRIMARY_SYMBOL"
export PROPR_LEVERAGE="$OPERATOR_LEVERAGE"
export PROPR_REQUIRE_HEALTHY_CORE="$(bool_to_yes_no 'propr_require_healthy_core')"
export DATA_SOURCE="live"
export HYPERLIQUID_COIN="$OPERATOR_PRIMARY_COIN"
export HYPERLIQUID_INTERVAL="$(bashio::config 'hyperliquid_interval')"
export HYPERLIQUID_LOOKBACK_BARS="$(bashio::config 'hyperliquid_lookback_bars')"
export SCAN_MARKETS="$OPERATOR_MARKETS"
export SCAN_CONFIRM="YES"
export TRADING_JOURNAL_PATH="$OPERATOR_JOURNAL_PATH"
export RUNNER_STATUS_PATH="$OPERATOR_RUNTIME_STATUS_PATH"
export TRADING_AGENT_LIVE_STATUS_PATH="$OPERATOR_LIVE_STATUS_PATH"

PANEL_DIR="/config/www/trading-agent"
PANEL_ASSET_SOURCE="$APP_PATH/ha_addons/trading_agent/panel/admin-panel.js"
PANEL_ASSET_TARGET="$PANEL_DIR/admin-panel.js"
PANEL_JOURNAL_TABLE_PATH="$PANEL_DIR/journal_table.json"
PANEL_LIVE_STATUS_PATH="$PANEL_DIR/live_status.json"

# Extract version for cache-busting
ADDON_VERSION=$(sed -n 's/^version: "\([^"]*\)".*/\1/p' "$APP_PATH/ha_addons/trading_agent/config.yaml" | tr -d '\r')

mkdir -p "$PANEL_DIR"
if [[ -f "$PANEL_ASSET_SOURCE" ]]; then
    # Inject version placeholder and serve directly (HA needs synchronous customElements.define)
    sed "s/__PANEL_VERSION__/${ADDON_VERSION}/g" "$PANEL_ASSET_SOURCE" \
        > "$PANEL_ASSET_TARGET"

    # Write version file (used by _checkPanelVersion() in-panel auto-reload)
    printf '%s' "$ADDON_VERSION" > "$PANEL_DIR/panel_version.txt"

    # Remove old versioned files from previous loader approach
    find "$PANEL_DIR" -name "admin-panel-*.js" -delete 2>/dev/null || true
fi

# Deploy journal delete helper script to /share (called by HA shell_command)
cat > "$DATA_PATH/delete_journal_entries.py" << 'DELETEPY'
import json, sys
from pathlib import Path

targets = json.loads(sys.argv[1])
for env in ("beta", "prod"):
    p = Path(f"/share/trading-agent-data/trading_journal_{env}.jsonl")
    if not p.exists():
        continue
    kept = []
    for line in p.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except Exception:
            kept.append(line)
            continue
        if not any(
            e.get("entry_timestamp") == t.get("entry_timestamp")
            and e.get("symbol") == t.get("symbol")
            and e.get("entry_type") == t.get("entry_type")
            and e.get("status") == t.get("status")
            for t in targets
        ):
            kept.append(line)
    p.write_text("\n".join(kept) + "\n", "utf-8")
DELETEPY

# Also copy panel assets to /share for host-side sync (proven path)
PANEL_SHARE_DIR="$DATA_PATH/panel"
mkdir -p "$PANEL_SHARE_DIR"
if [[ -d "$PANEL_DIR" ]]; then
    cp "$PANEL_DIR"/*.js "$PANEL_SHARE_DIR/" 2>/dev/null || true
    cp "$PANEL_DIR/panel_version.txt" "$PANEL_SHARE_DIR/" 2>/dev/null || true
fi

# Auto-update panel cache-buster in HA configuration.
# panel_custom does not support hot-reload in HA — a core restart is required
# whenever the module_url changes. This block detects a version mismatch,
# patches configuration.yaml automatically, and triggers the restart.
HA_CONFIG="/config/configuration.yaml"
if [[ -f "$HA_CONFIG" ]] && grep -q "admin-panel\.js" "$HA_CONFIG" 2>/dev/null; then
    # Extract existing ?v= value (empty string if no ?v= present yet)
    CURRENT_V=$(sed -n 's/.*admin-panel\.js?v=\([^"'"'"' ]*\).*/\1/p' "$HA_CONFIG" 2>/dev/null | head -1)
    if [[ "$CURRENT_V" != "$ADDON_VERSION" ]]; then
        if [[ -n "$CURRENT_V" ]]; then
            # Replace existing ?v=X.Y.Z with new version
            sed -i "s|admin-panel\.js?v=[^\"']*|admin-panel.js?v=${ADDON_VERSION}|g" "$HA_CONFIG"
            bashio::log.info "Panel cache-buster updated ($CURRENT_V → $ADDON_VERSION)"
        else
            # No ?v= present yet — append it to the module_url line
            sed -i "s|admin-panel\.js\([\"']\)|admin-panel.js?v=${ADDON_VERSION}\1|g" "$HA_CONFIG"
            bashio::log.info "Panel cache-buster added (→ ${ADDON_VERSION})"
        fi
        bashio::log.info "Restarting HA core to apply new panel version (panel_custom requires restart)..."
        curl -s -X POST \
            -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
            -H "Content-Type: application/json" \
            http://supervisor/core/restart || \
        curl -s -X POST \
            -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
            -H "Content-Type: application/json" \
            http://supervisor/homeassistant/restart || true
        exit 0
    fi
fi

# Write challenges.json for admin panel challenge selector
python -c "
import json
from broker.propr_client import ProprClient
from config.propr_config import ProprConfig
import os
try:
    env = os.environ.get('PROPR_ENV', 'beta')
    key = os.environ.get('PROPR_BETA_API_KEY') if env == 'beta' else os.environ.get('PROPR_PROD_API_KEY')
    url = os.environ.get('PROPR_BETA_API_URL', 'https://api.beta.propr.xyz/v1') if env == 'beta' else os.environ.get('PROPR_PROD_API_URL', 'https://api.propr.xyz/v1')
    config = ProprConfig(environment=env, api_key=key, base_url=url)
    client = ProprClient(config)
    attempts_raw = client.get_challenge_attempts()
    items = attempts_raw.get('data', []) if isinstance(attempts_raw, dict) else attempts_raw
    active = [a for a in items if a.get('status') == 'active']
    result = []
    for a in active:
        attempt_id = a.get('attemptId') or a.get('attempt_id') or a.get('id', '')
        detail = client.get_challenge_attempt(attempt_id) if attempt_id else {}
        challenge = detail.get('challenge', {}) or {}
        result.append({
            'challenge_id': a.get('challengeId') or a.get('challenge_id', ''),
            'attempt_id': attempt_id,
            'account_id': a.get('accountId') or a.get('account_id', ''),
            'name': challenge.get('name') or challenge.get('title', ''),
            'initial_balance': challenge.get('initialBalance', ''),
        })
    with open('$PANEL_DIR/challenges.json', 'w') as f:
        json.dump(result, f, ensure_ascii=True)
except Exception as e:
    print(f'Challenges fetch failed (non-critical): {e}')
    with open('$PANEL_DIR/challenges.json', 'w') as f:
        f.write('[]')
" 2>&1 || bashio::log.warning "Challenges fetch failed (non-critical)"
cp "$PANEL_DIR/challenges.json" "$PANEL_SHARE_DIR/challenges.json" 2>/dev/null || true

# Refresh asset registry (auto-discovers tradeable assets from Hyperliquid)
ASSET_REGISTRY_PATH="$DATA_PATH/asset_registry.json"
python -c "from broker.asset_registry import AssetRegistry; AssetRegistry(cache_path='$ASSET_REGISTRY_PATH').ensure_fresh()" 2>&1 || bashio::log.warning "Asset registry refresh failed (non-critical)"
cp "$ASSET_REGISTRY_PATH" "$PANEL_DIR/asset_registry.json" 2>/dev/null || true
cp "$ASSET_REGISTRY_PATH" "$PANEL_SHARE_DIR/asset_registry.json" 2>/dev/null || true

bashio::log.info "Starting Trading Agent one-shot run"
bashio::log.info "Mode: $OPERATOR_MODE"
bashio::log.info "Environment: $OPERATOR_ENVIRONMENT"
bashio::log.info "Markets: $OPERATOR_MARKETS"

run_started_at="$(date -Iseconds)"
run_exit_code=0

case "$OPERATOR_MODE" in
    scharf)
        export SCAN_ALLOW_SUBMIT="YES"
        export MANUAL_WRITE_CONFIRM="NO"
        export MANUAL_ORDER_TYPES_CONFIRM="NO"
        log_cmd_lines python scripts/multi_market_scan.py || run_exit_code=$?
        ;;
    preflight)
        export SCAN_ALLOW_SUBMIT="NO"
        export MANUAL_WRITE_CONFIRM="NO"
        export MANUAL_ORDER_TYPES_CONFIRM="NO"
        log_cmd_lines python run_test_suite.py --suite preflight --pytest-arg=-q --status-path "$OPERATOR_TEST_STATUS_PATH" --log-path "$OPERATOR_TEST_LOG_PATH" || run_exit_code=$?
        ;;
    beta_write)
        export SCAN_ALLOW_SUBMIT="NO"
        export MANUAL_WRITE_CONFIRM="YES"
        export MANUAL_ORDER_TYPES_CONFIRM="YES"
        log_cmd_lines python run_test_suite.py --suite beta_write --allow-live-beta-writes --status-path "$OPERATOR_TEST_STATUS_PATH" --log-path "$OPERATOR_TEST_LOG_PATH" || run_exit_code=$?
        ;;
    *)
        bashio::log.fatal "Unsupported operator mode: $OPERATOR_MODE"
        exit 1
        ;;
esac

run_finished_at="$(date -Iseconds)"

python journal_snapshot.py --path "$OPERATOR_JOURNAL_PATH" --limit 200 > "$OPERATOR_JOURNAL_SNAPSHOT_PATH" || true
python journal_table.py --path "$OPERATOR_JOURNAL_PATH" --output-path "$OPERATOR_JOURNAL_TABLE_PATH" || true
cp "$OPERATOR_JOURNAL_TABLE_PATH" "$PANEL_JOURNAL_TABLE_PATH" || true
python scripts/sync_live_status.py --output-path "$OPERATOR_LIVE_STATUS_PATH" || true
cp "$OPERATOR_LIVE_STATUS_PATH" "$PANEL_LIVE_STATUS_PATH" || true
python run_summary.py --mode "$OPERATOR_MODE" --environment "$OPERATOR_ENVIRONMENT" --started-at "$run_started_at" --finished-at "$run_finished_at" --exit-code "$run_exit_code" --journal-path "$OPERATOR_JOURNAL_PATH" --test-status-path "$OPERATOR_TEST_STATUS_PATH" --output-path "$OPERATOR_RUN_SUMMARY_PATH" || true

exit "$run_exit_code"
