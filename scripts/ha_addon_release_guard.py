import re
import sys
from pathlib import Path


ADDON_CONFIG_PATH = Path("ha_addons/trading_agent/config.yaml")
COMMIT_SUBJECT_RE = re.compile(r"^\[(\d+\.\d+\.\d+)\] - (.+)$")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SystemExit(f"ERROR: Missing file: {path.as_posix()}")


def _extract_addon_version(config_text: str) -> str:
    # Minimal YAML parse: look for `version: "X.Y.Z"` (config is simple and controlled).
    m = re.search(r'(?m)^\s*version:\s*["\']?(\d+\.\d+\.\d+)["\']?\s*$', config_text)
    if not m:
        raise SystemExit(
            f"ERROR: Could not find a semver `version:` in {ADDON_CONFIG_PATH.as_posix()}"
        )
    return m.group(1)


def validate_commit_subject(subject: str) -> str:
    m = COMMIT_SUBJECT_RE.match(subject.strip())
    if not m:
        raise SystemExit(
            "ERROR: Commit subject must match: [X.Y.Z] - Short summary\n"
            "Example: [0.6.1] - Fix HA add-on slug"
        )
    return m.group(1)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: ha_addon_release_guard.py <commit-subject>", file=sys.stderr)
        return 2

    subject = argv[1]
    version_in_subject = validate_commit_subject(subject)

    config_text = _read_text(ADDON_CONFIG_PATH)
    version_in_config = _extract_addon_version(config_text)

    if version_in_subject != version_in_config:
        print(
            "ERROR: Version mismatch.\n"
            f"- Commit subject: {version_in_subject}\n"
            f"- {ADDON_CONFIG_PATH.as_posix()}: {version_in_config}\n"
            "\nFix by bumping the add-on version or updating the commit subject.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

