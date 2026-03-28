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
export PYTHONPATH="$APP_PATH"
export TRADING_AGENT_DATA_PATH="$DATA_PATH"
export TRADING_AGENT_OPERATOR_CONFIG_PATH="$OPERATOR_CONFIG_PATH"

operator_env_output="$("$VIRTUAL_ENV/bin/python" operator_config.py export-env --path "$OPERATOR_CONFIG_PATH" 2>&1)" || {
    bashio::log.fatal "Failed to resolve operator config"
    bashio::log.fatal "$operator_env_output"
    exit 1
}

if [[ "$operator_env_output" == \{* ]]; then
    bashio::log.fatal "Operator config export returned an error payload"
    bashio::log.fatal "$operator_env_output"
    exit 1
fi

eval "$operator_env_output"

export PROPR_ENV="$OPERATOR_ENVIRONMENT"
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

bashio::log.info "Starting Trading Agent one-shot run"
bashio::log.info "Mode: $OPERATOR_MODE"
bashio::log.info "Environment: $OPERATOR_ENVIRONMENT"
bashio::log.info "Markets: $OPERATOR_MARKETS"

run_exit_code=0

case "$OPERATOR_MODE" in
    scharf)
        export SCAN_ALLOW_SUBMIT="YES"
        export MANUAL_WRITE_CONFIRM="NO"
        export MANUAL_ORDER_TYPES_CONFIRM="NO"
        python scripts/multi_market_scan.py || run_exit_code=$?
        ;;
    preflight)
        export SCAN_ALLOW_SUBMIT="NO"
        export MANUAL_WRITE_CONFIRM="NO"
        export MANUAL_ORDER_TYPES_CONFIRM="NO"
        python run_test_suite.py --suite preflight --pytest-arg=-q --status-path "$OPERATOR_TEST_STATUS_PATH" --log-path "$OPERATOR_TEST_LOG_PATH" || run_exit_code=$?
        ;;
    beta_write)
        export SCAN_ALLOW_SUBMIT="NO"
        export MANUAL_WRITE_CONFIRM="YES"
        export MANUAL_ORDER_TYPES_CONFIRM="YES"
        python run_test_suite.py --suite beta_write --allow-live-beta-writes --status-path "$OPERATOR_TEST_STATUS_PATH" --log-path "$OPERATOR_TEST_LOG_PATH" || run_exit_code=$?
        ;;
    *)
        bashio::log.fatal "Unsupported operator mode: $OPERATOR_MODE"
        exit 1
        ;;
esac

python journal_snapshot.py --path "$OPERATOR_JOURNAL_PATH" --limit 20 > "$OPERATOR_JOURNAL_SNAPSHOT_PATH" || true

exit "$run_exit_code"
