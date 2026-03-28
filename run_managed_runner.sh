#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/opt/trading-agent"

cd "$PROJECT_ROOT"
source "$PROJECT_ROOT/.venv/bin/activate"
exec python "$PROJECT_ROOT/managed_runner.py"
