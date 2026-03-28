from __future__ import annotations

from pathlib import Path
import runpy


if __name__ == "__main__":
    script_path = Path(__file__).resolve().parent / "deploy" / "raspberry_pi" / "managed_runner.py"
    runpy.run_path(str(script_path), run_name="__main__")
