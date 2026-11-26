"""The repo-root VERSION file is the single source of the app's version."""

import json
from pathlib import Path

from app.core.version import APP_VERSION

REPO = Path(__file__).resolve().parents[2]


def test_backend_reports_the_version_file(client):
    version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    assert APP_VERSION == version
    assert client.get("/api/health").json()["version"] == version
    assert client.get("/openapi.json").json()["info"]["version"] == version


def test_frontend_package_matches_the_version_file():
    """The footer reads VERSION at build time; keep package.json's metadata from drifting."""
    package = json.loads((REPO / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert package["version"] == (REPO / "VERSION").read_text(encoding="utf-8").strip()
