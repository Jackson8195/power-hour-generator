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


def _measure(monkeypatch, stats_json: str):
    """Run RenderPipeline._measure_loudnorm against a fake ffmpeg that prints ``stats_json``."""
    import asyncio

    from app.services.ffmpeg import RenderPipeline

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return b"", f"[Parsed_loudnorm_0 @ 0x1]\n{stats_json}\n".encode()

    async def fake_exec(*cmd, **_):
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    pipeline = RenderPipeline(clips=[], output_path="x.mp4", resolution="640x360",
                              transition_type="crossfade", include_countdown=False)
    return asyncio.run(pipeline._measure_loudnorm("clip.mp4", 0.0, 4.0))


def test_loudnorm_measurement_of_silence_falls_back_to_single_pass(monkeypatch):
    silent = ('{"input_i": "-inf", "input_tp": "-inf", "input_lra": "0.00", '
              '"input_thresh": "-70.00", "target_offset": "inf"}')
    assert _measure(monkeypatch, silent) is None  # caller then uses single-pass loudnorm


def test_loudnorm_measurement_of_normal_audio_is_kept(monkeypatch):
    normal = ('{"input_i": "-14.20", "input_tp": "-0.50", "input_lra": "6.10", '
              '"input_thresh": "-24.30", "target_offset": "0.40"}')
    assert _measure(monkeypatch, normal)["input_i"] == "-14.20"
