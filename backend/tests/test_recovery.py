"""Jobs left running when the backend stopped must not stay 'running' forever."""

from fastapi.testclient import TestClient

from app.main import app


def test_interrupted_jobs_are_failed_on_startup(client, project_id, make_clip, db):
    stuck_clip = make_clip(status="DOWNLOADING")
    analyzing_clip = make_clip(status="ANALYZING")
    ready_clip = make_clip(status="READY")
    db.execute("INSERT INTO renders (project_id, output_path, status, progress, resolution, error_message)"
               " VALUES (?, '', 'RENDERING', 10, '1280x720', '')", (project_id,))
    db.execute("INSERT INTO renders (project_id, output_path, status, progress, resolution, error_message)"
               " VALUES (?, '', 'QUEUED', 0, '1280x720', '')", (project_id,))
    db.commit()

    assert client.get(f"/api/render/active/{project_id}").json() is not None

    with TestClient(app):  # a fresh startup, as after a restart
        pass

    status = lambda cid: db.execute("SELECT status FROM clips WHERE id=?", (cid,)).fetchone()[0]
    assert status(stuck_clip) == "ERROR"
    assert status(analyzing_clip) == "ERROR"
    assert status(ready_clip) == "READY"
    assert db.execute(
        "SELECT COUNT(*) FROM renders WHERE status IN ('QUEUED','RENDERING')"
    ).fetchone()[0] == 0
    assert client.get(f"/api/render/active/{project_id}").json() is None
