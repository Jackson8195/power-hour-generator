"""The app's version, read from the repo-root VERSION file (the one place to bump it)."""

from pathlib import Path

# backend/app/core/version.py -> repo root locally, /app in the Docker image (both hold VERSION).
_VERSION_FILE = Path(__file__).resolve().parents[3] / "VERSION"


def read_version() -> str:
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0-dev"
    except OSError:
        return "0.0.0-dev"


APP_VERSION = read_version()
