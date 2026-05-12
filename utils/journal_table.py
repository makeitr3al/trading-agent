from __future__ import annotations

from pathlib import Path
from typing import Any

from utils.journal_snapshot import resolve_trading_journal_path
from utils.journal_table_core import build_journal_table_payload


def build_journal_table(path: str | Path | None = None) -> dict[str, Any]:
    journal_path = Path(path) if path is not None else resolve_trading_journal_path()
    return build_journal_table_payload(journal_path)
