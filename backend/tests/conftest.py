"""Test setup: isolate the DB and media dirs *before* the app is imported."""

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="power_hour_tests_"))
DB_PATH = _TMP / "test.db"

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH}"
os.environ["MEDIA_DIR"] = str(_TMP / "media")
os.environ["RENDER_DIR"] = str(_TMP / "media" / "renders")
# Never call the paid image API from tests: AI transition art falls back to bundled art.
os.environ["OPENAI_IMAGE_MODEL"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def db():
    """Plain sqlite3 handle for seeding/inspecting rows without the async engine."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.commit()
    conn.close()


@pytest.fixture()
def project_id(client):
    return client.post("/api/projects/", json={"name": "Test Hour"}).json()["id"]


@pytest.fixture()
def make_clip(client, db, project_id):
    """Create a clip; extra kwargs are written straight to the clips table."""

    def _make(youtube_id="abc123", **columns):
        resp = client.post(
            f"/api/clips/?project_id={project_id}",
            json={"source_url": "https://example.com", "youtube_id": youtube_id},
        )
        clip_id = resp.json()["id"]
        if columns:
            sets = ", ".join(f"{k} = ?" for k in columns)
            db.execute(f"UPDATE clips SET {sets} WHERE id = ?", [*columns.values(), clip_id])
            db.commit()
        return clip_id

    return _make


@pytest.fixture()
def media_file():
    """Create a dummy file under the managed media dir."""

    def _make(subdir: str, name: str) -> Path:
        path = settings.media_dir / subdir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return path

    return _make
