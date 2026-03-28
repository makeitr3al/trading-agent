from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_runtime_status(path: str | Path, payload: dict[str, Any]) -> Path:
    status_path = Path(path)
    status_path.parent.mkdir(parents=True, exist_ok=True)

    serialized_payload = dict(payload)
    serialized_payload["updated_at"] = utc_now_iso()

    with status_path.open("w", encoding="utf-8") as handle:
        json.dump(serialized_payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")

    return status_path
