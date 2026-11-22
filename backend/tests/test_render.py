"""Render validation (no render without a valid saved selection) and output naming."""

from app.api.render import _build_output_path


def test_render_requires_a_clip_with_a_selection(client, project_id, make_clip, media_file):
    media = media_file("downloads", "r1.mp4")
    # READY but no saved selection (start == end == 0).
    make_clip(file_path=str(media), duration=100.0, status="READY", start_time=0.0, end_time=0.0)
    resp = client.post(f"/api/render/{project_id}", json={})
    assert resp.status_code == 400


def test_render_ignores_clips_that_are_not_ready(client, project_id, make_clip, media_file):
    media = media_file("downloads", "r2.mp4")
    make_clip(file_path=str(media), duration=100.0, status="ERROR", start_time=0.0, end_time=30.0)
    assert client.post(f"/api/render/{project_id}", json={}).status_code == 400


def test_render_rejects_missing_media(client, project_id, make_clip):
    make_clip(file_path="/nonexistent/x.mp4", duration=60.0, status="READY",
              start_time=0.0, end_time=60.0)
    resp = client.post(f"/api/render/{project_id}", json={})
    assert resp.status_code == 400
    assert "Missing media" in resp.json()["detail"]


def test_output_path_is_sanitized():
    for name in ["../../etc/passwd", "a/b\\c", "Rock & Roll!", "", "   "]:
        path = _build_output_path(name, 1, 2)
        assert path.parent.name == "renders"
        assert "/" not in path.name and ".." not in path.name
    assert _build_output_path("Rock & Roll!", 1, 2).name == "power_hour_rock_roll_1_render_2.mp4"


def test_render_reports_skipped_clips(client, project_id, make_clip, media_file, monkeypatch):
    import app.api.render as render_api

    async def noop_render(*args, **kwargs):
        return None

    monkeypatch.setattr(render_api, "_run_render", noop_render)

    good = media_file("clips", "good.mp4")
    make_clip(file_path=str(good), duration=60.0, status="READY", start_time=0.0, end_time=60.0)
    make_clip(status="PENDING")
    resp = client.post(f"/api/render/{project_id}", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["clips_included"] == 1
    assert len(body["clips_skipped"]) == 1


def test_cancel_render_deletes_row_and_file(client, project_id, db, media_file):
    out = media_file("renders", "cancel_me.mp4")
    db.execute(
        "INSERT INTO renders (project_id, output_path, status, progress, resolution, error_message)"
        " VALUES (?, ?, 'COMPLETE', 100, '1280x720', '')", (project_id, str(out)),
    )
    db.commit()
    render_id = db.execute("SELECT MAX(id) FROM renders").fetchone()[0]
    assert client.delete(f"/api/render/{render_id}").status_code == 200
    assert not out.exists()
    assert client.delete(f"/api/render/{render_id}").status_code == 404
