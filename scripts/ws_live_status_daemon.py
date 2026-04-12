"""Maintain live_status.json from the Propr WebSocket (PnL, open positions).

The Home Assistant add-on and scheduled scans update live_status via REST only when
they run. This daemon keeps account_unrealized_pnl, account_open_positions_count, and
optional open_positions_summary fresh between those runs.

Deployment (separate long-lived process):
  Run alongside the trading agent or HA host with the same environment as Propr API
  access, and point TRADING_AGENT_LIVE_STATUS_PATH (or OPERATOR_LIVE_STATUS_PATH) at
  the same live_status.json the panel / HA sensor reads (often under TRADING_AGENT_DATA_PATH).

  Typical Raspberry Pi (systemd): WorkingDirectory to the repo, EnvironmentFile to .env,
  ExecStart to this venv's python running this script, Restart=always.

Environment:
  PROPR_ENV, PROPR_BETA_* / PROPR_PROD_* credentials, optional PROPR_CHALLENGE_ID,
  PROPR_*_WS_URL overrides, TRADING_AGENT_DATA_PATH, TRADING_AGENT_LIVE_STATUS_PATH.

Run (repo venv, any current working directory):
  .\\.venv\\Scripts\\python.exe scripts\\ws_live_status_daemon.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from broker.challenge_service import get_active_challenge_context
from broker.propr_client import ProprClient
from broker.propr_ws import ProprWebSocketClient
from utils.env_loader import load_propr_config_from_env
from utils.live_status import resolve_live_status_path, write_live_status_from_state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("ws_live_status_daemon")


def main() -> None:
    live_status_path = resolve_live_status_path()
    propr_config = load_propr_config_from_env()
    environment = propr_config.environment
    client = ProprClient(propr_config)

    challenge_context = get_active_challenge_context(client)
    if challenge_context is None:
        write_live_status_from_state(
            environment=environment,
            state=None,
            source="poll",
            last_error="ws daemon: no active challenge",
            path=live_status_path,
        )
        logger.error("No active challenge; wrote error to %s and exiting.", live_status_path)
        sys.exit(1)

    account_id = challenge_context.account_id
    logger.info(
        "Starting WebSocket live status for account_id=%s env=%s ws=%s",
        account_id,
        environment,
        propr_config.websocket_url,
    )

    ws_client = ProprWebSocketClient(propr_config)
    try:
        asyncio.run(ws_client.run_forever(account_id, path=live_status_path))
    except KeyboardInterrupt:
        logger.info("Stopped by user.")


if __name__ == "__main__":
    main()
