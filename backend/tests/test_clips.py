"""Clip review flow: draft range validation and the commit (trim) transition."""

from pathlib import Path

import app.api.clips as clips_api


def _patch_clip(client, clip_id, **body):
    return client.patch(f"/api/clips/{clip_id}", json=body)


def test_patch_rejects_empty_range(client, make_clip):
    clip_id = make_clip(duration=100.0)
    assert _patch_clip(client, clip_id, start_time=30, end_time=30).status_code == 400
    assert _patch_clip(client, clip_id, start_time=40, end_time=10).status_code == 400


def test_patch_checks_single_field_against_stored_value(client, make_clip):
    clip_id = make_clip(duration=100.0, start_time=20.0, end_time=50.0)
    # Moving only the end before the stored start must fail.
    assert _patch_clip(client, clip_id, end_time=10).status_code == 400


def test_patch_clamps_end_to_duration_and_rejects_start_past_end(client, make_clip):
    clip_id = make_clip(duration=100.0)
    resp = _patch_clip(client, clip_id, start_time=70, end_time=500)
    assert resp.status_code == 200
    assert resp.json()["end_time"] == 100.0
    assert _patch_clip(client, clip_id, start_time=100, end_time=120).status_code == 400


def test_commit_trims_then_deletes_source(client, make_clip, media_file, monkeypatch):
    source = media_file("downloads", "vid_1.mp4")
    clip_id = make_clip(file_path=str(source), duration=200.0, status="READY")

    async def fake_extract(source_path, output_path, start_time, end_time):
        assert source.exists(), "source must still exist while ffmpeg runs"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"clip")

    monkeypatch.setattr(clips_api, "extract_clip_segment", fake_extract)

    resp = client.post(f"/api/clips/{clip_id}/commit", json={"start_time": 10, "end_time": 70})
    assert resp.status_code == 200
    body = resp.json()
    assert body["duration"] == 60
    assert (body["start_time"], body["end_time"]) == (0.0, 60)
    assert not source.exists()


def test_commit_failure_keeps_source(client, make_clip, media_file, monkeypatch):
    source = media_file("downloads", "vid_2.mp4")
    clip_id = make_clip(file_path=str(source), duration=200.0, status="READY")

    async def boom(**kwargs):
        raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr(clips_api, "extract_clip_segment", boom)

    resp = client.post(f"/api/clips/{clip_id}/commit", json={"start_time": 10, "end_time": 70})
    assert resp.status_code == 500
    assert source.exists()


def test_commit_clamps_to_duration(client, make_clip, media_file, monkeypatch):
    source = media_file("downloads", "vid_3.mp4")
    clip_id = make_clip(file_path=str(source), duration=90.0, status="READY")
    seen = {}

    async def fake_extract(source_path, output_path, start_time, end_time):
        seen.update(start=start_time, end=end_time)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"clip")

    monkeypatch.setattr(clips_api, "extract_clip_segment", fake_extract)
    resp = client.post(f"/api/clips/{clip_id}/commit", json={"start_time": 50, "end_time": 150})
    assert resp.status_code == 200
    assert seen == {"start": 50, "end": 90.0}
    assert resp.json()["duration"] == 40.0


def test_deleting_clip_removes_its_media(client, make_clip, media_file):
    media = media_file("clips", "gone_1.mp4")
    clip_id = make_clip(file_path=str(media), duration=60.0)
    assert client.delete(f"/api/clips/{clip_id}").status_code == 200
    assert not media.exists()
