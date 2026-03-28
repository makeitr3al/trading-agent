from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.runtime_status import write_runtime_status


def test_write_runtime_status_persists_json_with_updated_at(tmp_path: Path) -> None:
    status_path = tmp_path / "runner_status.json"

    write_runtime_status(
        status_path,
        {
            "runner_state": "idle",
            "symbol": "BTC/USDC",
        },
    )

    persisted = json.loads(status_path.read_text(encoding="utf-8"))
    assert persisted["runner_state"] == "idle"
    assert persisted["symbol"] == "BTC/USDC"
    assert isinstance(persisted["updated_at"], str)
