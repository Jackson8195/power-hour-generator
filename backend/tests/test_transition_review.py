"""Drink-art transitions, the AI transition review flow, and the builder's countdown/ending wrap."""

import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.api import ai_transitions as review_api
from app.api import auto_generate as ag_api
from app.api.changeover import _wrap_options
from app.core.config import settings
from app.models.schemas import AutoGenerateProposalItem
from app.services import ai_transitions as ait
from app.services import auto_generate as ag
from app.services import transition_fx as fx

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


# ─── filters and assets ─────────────────────────────────

def test_bundled_drink_art_ships_with_the_app():
    names = {p.name for p in fx.bundled_art()}
    assert {"shot_glass.jpg", "beer_mug.jpg"} <= names
    assert fx.pick_bundled_art(0) != fx.pick_bundled_art(1)


def test_art_card_has_corner_countdown_call_word_and_cue():
    graph = fx.art_card_filter(1280, 720, 5.5, "0xFFE600", "horn", recorded=False)
    assert "corner_3.txt" in graph and "corner_1.txt" in graph and "hit.txt" in graph
    assert "[0:v]" in graph and "aevalsrc" in graph and "[v]" in graph and "[a]" in graph
    recorded = fx.art_card_filter(1280, 720, 5.5, "0xFFE600", "horn", recorded=True)
    assert "[1:a]" in recorded and "amix" in recorded  # the recorded cue plays over the ticks


def test_clip_stinger_appends_the_drink_art_only_when_asked():
    with_ending = fx.clip_stinger_filter(1280, 720, 5.0, "0xFFE600", True, "buzzer", True, True, False)
    assert "concat=n=2" in with_ending and "[1:v]" in with_ending and "corner_3.txt" in with_ending
    countdown_only = fx.clip_stinger_filter(1280, 720, 5.0, "0xFFE600", True, "horn", True, False, False)
    assert "concat" not in countdown_only and "corner_3.txt" in countdown_only
    plain = fx.clip_stinger_filter(1280, 720, 5.0, "0xFFE600", False, "horn", False, False, False)
    assert "corner_" not in plain and "anullsrc" in plain  # a silent clip still gets an audio track


def test_recorded_sounds_are_offered_only_when_their_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(fx, "SOUND_DIR", tmp_path)
    assert fx.available_sounds() == () and fx.usable_sound("clink") == fx.DEFAULT_SOUND == "can"
    (tmp_path / "glass_clink.ogg").write_bytes(b"x")
    assert fx.available_sounds() == ("clink",) and fx.usable_sound("clink") == "clink"
    assert fx.usable_sound("bell") == "clink"  # the default's file is missing: first available
    (tmp_path / "beer_can.mp3").write_bytes(b"x")
    assert fx.usable_sound("bell") == "can" and fx.sound_file("can").name == "beer_can.mp3"
    # the scrapped sounds are not cues any more, even with a file present
    (tmp_path / "air_horn.ogg").write_bytes(b"x")
    assert fx.sound_file("horn") is None and "horn" not in fx.available_sounds()


def test_bundled_sound_pack_is_complete():
    """Every cue the app offers ships with a recording; can is the default."""
    assert fx.available_sounds() == fx.SOUNDS == ("can", "clink", "pop", "pour", "cheer", "bell")
    assert fx.usable_sound("horn") == "can" and fx.usable_sound("buzzer") == "can"


def test_builder_wrap_options_only_accept_known_values():
    ok = _wrap_options("true", "clink", fx.bundled_art()[0].name, "shot!")
    assert ok["countdown"] and ok["sound"] == "clink" and ok["word"] == "SHOT!" and ok["art"]
    assert _wrap_options("true", "horn", None, "")["sound"] == ""  # scrapped
    bad = _wrap_options("false", "rm -rf", "../../etc/passwd", "'; drop")
    assert not bad["countdown"] and bad["sound"] == "" and bad["art"] is None and bad["word"] == "DRINK!"


def test_transition_assets_catalog(client):
    data = client.get("/api/changeover/assets/catalog").json()
    assert data["sounds"] == ["can", "clink", "pop", "pour", "cheer", "bell"] and "DRINK!" in data["words"]
    first = data["art"][0]
    assert client.get(first["url"]).status_code == 200
    assert client.get("/api/changeover/assets/art/..%2F..%2Fmain.py").status_code == 404


# ─── real renders (skipped without ffmpeg) ──────────────

def _probe(path) -> tuple[float, bool]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    import json

    data = json.loads(out)
    kinds = {s["codec_type"] for s in data["streams"]}
    return float(data["format"]["duration"]), "audio" in kinds


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg not installed")
def test_real_art_card_and_clip_with_recorded_cue(tmp_path, monkeypatch):
    import asyncio

    # a recorded cue in the sound pack is used instead of the generated one
    sounds = tmp_path / "sounds"
    sounds.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=3",
                    str(sounds / "glass_clink.wav")], check=True)
    monkeypatch.setattr(fx, "SOUND_DIR", sounds)
    clip = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=320x240:d=8",
                    "-f", "lavfi", "-i", "sine=f=220:d=8", "-shortest", str(clip)], check=True)
    art = str(fx.bundled_art()[0])

    card = tmp_path / "card.mp4"
    length = asyncio.run(fx.build_art_card(str(card), art, resolution="320x180", sound="clink"))
    duration, has_audio = _probe(card)
    assert length == fx.CARD_SECONDS and abs(duration - length) < 0.2 and has_audio

    out = tmp_path / "clip_out.mp4"
    length = asyncio.run(fx.build_clip_with_stinger(
        str(out), str(clip), start=1.0, clip_seconds=4.0, resolution="320x180", art_path=art, sound="clink"))
    duration, has_audio = _probe(out)
    assert length == pytest.approx(4.0 + fx.STINGER_SECONDS) and abs(duration - length) < 0.25 and has_audio

    wrapped = tmp_path / "wrapped.mp4"
    length = asyncio.run(fx.build_clip_with_stinger(str(wrapped), str(clip), resolution="320x180"))
    duration, _ = _probe(wrapped)
    assert abs(duration - 8.0) < 0.25 and abs(length - 8.0) < 0.25  # whole clip, countdown only


# ─── review flow ────────────────────────────────────────

def _wait_idle(client, project_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/ai-transitions/{project_id}").json()
        if data["state"] == "idle" and all(t["status"] != "building" for t in data["transitions"]):
            return data
        time.sleep(0.05)
    raise AssertionError("transitions never finished building")


@pytest.fixture()
def fake_builds(monkeypatch):
    calls = {"plans": []}

    async def fake_plan(theme, count, sources, avoid_titles=None, transition_prompt="", avoid_labels=None):
        calls["plans"].append({"theme": theme, "prompt": transition_prompt, "avoid": list(avoid_labels or [])})
        n = len(calls["plans"])
        return ait.sanitize_specs(
            [{"label": f"plan{n}-{i}", "headline": f"P{n}{i}", "art_prompt": "a shot glass"} for i in range(count)],
            count, sources,
        )

    async def fake_card(spec, output_path, resolution):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"x")
        return fx.CARD_SECONDS

    async def no_playlist(db, project_id):
        return set(), []

    monkeypatch.setattr(ait, "plan_transitions", fake_plan)
    monkeypatch.setattr(ait, "_build_card", fake_card)
    monkeypatch.setattr(ait, "_playlist", no_playlist)
    return calls


def test_generate_review_regenerate_trash_and_add(client, project_id, fake_builds):
    resp = client.post(f"/api/ai-transitions/{project_id}/generate",
                       json={"prompt": "golden microphones", "count": 2, "sources": "cards"})
    assert resp.status_code == 202
    data = _wait_idle(client, project_id)
    items = data["transitions"]
    assert [t["status"] for t in items] == ["ready", "ready"] and all(t["preview_url"] for t in items)
    assert fake_builds["plans"][0]["prompt"] == "golden microphones"

    first, second = items
    old_file = settings.changeover_dir / Path(first["preview_url"]).name
    assert old_file.exists()
    resp = client.post(f"/api/ai-transitions/{project_id}/{first['id']}/regenerate", json={"prompt": "more gold"})
    assert resp.status_code == 202
    items = _wait_idle(client, project_id)["transitions"]
    redone = next(t for t in items if t["id"] == first["id"])
    assert redone["label"] != first["label"] and redone["preview_url"] != first["preview_url"]
    assert not old_file.exists()  # the replaced transition's file is cleaned up
    plan = fake_builds["plans"][-1]
    assert plan["prompt"] == "more gold" and second["label"] in plan["avoid"]  # told what to avoid

    assert client.delete(f"/api/ai-transitions/{project_id}/{second['id']}").status_code == 200
    assert client.post(f"/api/ai-transitions/{project_id}/add", json={"kind": "card"}).status_code == 202
    items = _wait_idle(client, project_id)["transitions"]
    assert len(items) == 2 and all(t["status"] == "ready" for t in items)
    assert items[-1]["position"] > items[0]["position"]  # added at the end of the cycle


def test_a_busy_project_refuses_overlapping_requests(client, project_id, fake_builds):
    ait._set_review(project_id, "building")
    try:
        resp = client.post(f"/api/ai-transitions/{project_id}/generate", json={"count": 2})
        assert resp.status_code == 409
        assert client.post(f"/api/ai-transitions/{project_id}/add", json={}).status_code == 409
    finally:
        ait._set_review(project_id, "idle")


def test_generated_art_is_kept_and_bundled_art_is_never_deleted(client, project_id, fake_builds, db):
    client.post(f"/api/ai-transitions/{project_id}/generate", json={"count": 1, "sources": "cards"})
    item = _wait_idle(client, project_id)["transitions"][0]
    art = db.execute("SELECT image_path FROM changover_clips WHERE id = ?", (item["id"],)).fetchone()[0]
    assert Path(art).parent == fx.ART_DIR  # no image model in tests: bundled drink art
    assert client.delete(f"/api/ai-transitions/{project_id}/{item['id']}").status_code == 200
    assert Path(art).exists()


# ─── approval keeps the reviewed set ────────────────────

def _proposal(ids):
    items = [
        AutoGenerateProposalItem(slot_index=i, requested_title=f"T{i}", requested_artist="A", youtube_id=vid,
                                 title=f"T{i}", artist="A", status="resolved")
        for i, vid in enumerate(ids)
    ]
    return ag.StoredProposal(proposal_id=f"p{time.time_ns()}", prompt="idol", normalized_prompt="idol",
                             items=items, expires_at=datetime.utcnow() + timedelta(hours=1), mode="music")


def test_approve_keeps_reviewed_transitions_and_resyncs_swapped_songs(client, db, monkeypatch):
    import asyncio

    started = []
    monkeypatch.setattr(ag_api, "start_auto_process_queue",
                        lambda job_id, project_id, clip_ids, transitions=None: started.append((clip_ids, transitions)))
    proposal = _proposal(["aaa", "bbb"])
    asyncio.run(ag.proposal_store.save(proposal))
    project_id = client.post(f"/api/auto-generate/proposals/{proposal.proposal_id}/project",
                             json={"project_name": "Idol"}).json()["project_id"]
    db.execute(
        "INSERT INTO changover_clips (project_id, origin, position, label, source_type, output_path, duration, "
        "status, error_message) VALUES (?, 'ai', 0, 'Golden mic', 'ai_card', '/x.mp4', 5.5, 'ready', '')",
        (project_id,),
    )
    db.commit()

    # the user swaps a song after reviewing transitions
    proposal.items[1] = proposal.items[1].model_copy(update={"youtube_id": "ccc", "title": "New"})
    resp = client.post(f"/api/auto-generate/proposals/{proposal.proposal_id}/approve", json={
        "project_id": project_id, "ai_transition_count": 4, "ai_transitions_reviewed": True})
    assert resp.status_code == 200, resp.text
    clip_ids, transitions = started[0]
    assert transitions is None  # nothing regenerated during the build
    ids = [r[0] for r in db.execute(
        "SELECT youtube_id FROM clips WHERE project_id = ? ORDER BY position", (project_id,))]
    assert ids == ["aaa", "ccc"] and len(clip_ids) == 2
    labels = [r[0] for r in db.execute("SELECT label FROM changover_clips WHERE project_id = ?", (project_id,))]
    assert labels == ["Golden mic"]


def test_approve_without_review_still_generates_during_the_build(client, monkeypatch):
    import asyncio

    started = []
    monkeypatch.setattr(ag_api, "start_auto_process_queue",
                        lambda job_id, project_id, clip_ids, transitions=None: started.append(transitions))
    proposal = _proposal(["ddd"])
    asyncio.run(ag.proposal_store.save(proposal))
    resp = client.post(f"/api/auto-generate/proposals/{proposal.proposal_id}/approve", json={
        "ai_transition_count": 3, "ai_transition_prompt": "gold confetti"})
    assert resp.status_code == 200, resp.text
    assert started[0].count == 3 and started[0].prompt == "gold confetti"


def test_theme_strips_the_generated_description_prefix():
    class P:
        description = "AI generated from prompt: golden era idol"
        name = "x"

    assert review_api._theme(P()) == "golden era idol"


def test_headline_less_art_cards_are_not_collapsed_by_dedupe():
    # the art-card plan has labels and art but no headline; three distinct ideas must survive
    raw = [{"label": f"Golden mic {i}", "art_prompt": f"shot glass scene {i}"} for i in range(3)]
    specs = ait.sanitize_specs(raw, 3, "cards")
    assert len(specs) == 3 and specs[0].headline == "Golden mic 0"
    assert len(ait.sanitize_specs(raw + raw, 6, "cards")) == 3  # true repeats still drop


# ─── re-trimming a video moment ─────────────────────────

@pytest.mark.skipif(not FFMPEG, reason="ffmpeg not installed")
def test_video_moment_keeps_the_whole_source_and_can_be_retrimmed(client, project_id, fake_builds, monkeypatch, tmp_path, db):
    """A video transition keeps its WHOLE download (so the user can watch it all and pick any
    range), ends with the user's own text over the video (no art card), and can be re-trimmed
    and re-texted."""
    from app.services.youtube import SearchResult

    source = tmp_path / "source.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=320x240:d=30",
                    "-f", "lavfi", "-i", "sine=f=220:d=30", "-shortest", str(source)], check=True)

    async def fake_search(query, max_results=8, music=False):
        return [SearchResult(youtube_id="vid1", title="funny audition", duration="0:30", thumbnail="")]

    async def fake_download(youtube_id, output_dir, file_stem):
        target = Path(output_dir) / f"{file_stem}.mp4"
        shutil.copyfile(source, target)
        return {"file_path": str(target), "duration": 30.0}

    async def fake_moment(path, source_seconds, clip_seconds):
        return 12.0, [0.2, 0.8, 0.5], 30.0

    monkeypatch.setattr(ait, "search_youtube", fake_search)
    monkeypatch.setattr(ait, "download_video", fake_download)
    monkeypatch.setattr(ait, "_pick_moment", fake_moment)
    monkeypatch.setattr(ait, "render_resolution", lambda: "320x180")

    client.post(f"/api/ai-transitions/{project_id}/generate",
                json={"count": 1, "sources": "youtube", "drink_text": "TAKE A SIP"})
    item = _wait_idle(client, project_id, timeout=60)["transitions"][0]
    assert item["kind"] == "youtube" and item["source_url"]
    assert item["drink_text"] == "TAKE A SIP"
    # trim times are seconds into the whole download
    assert (item["trim_start"], item["trim_end"]) == (12.0, 12.0 + fx.VIDEO_CLIP_SECONDS)
    assert item["source_seconds"] == 30.0 and item["waveform"] == [0.2, 0.8, 0.5]
    kept = settings.changeover_dir / Path(item["source_url"]).name
    assert _probe(kept)[0] == pytest.approx(30.0, abs=0.3)  # the whole video, not a window
    # clip + the held last frame with the text over it; no 2.2s art stinger any more
    assert item["duration"] == pytest.approx(fx.VIDEO_CLIP_SECONDS + fx.VIDEO_TAIL_SECONDS)

    old_preview = settings.changeover_dir / Path(item["preview_url"]).name
    resp = client.post(f"/api/ai-transitions/{project_id}/{item['id']}/trim", json={"start": 20.0, "end": 26.5})
    assert resp.status_code == 202, resp.text
    trimmed = _wait_idle(client, project_id, timeout=60)["transitions"][0]
    assert trimmed["status"] == "ready" and not trimmed["error_message"]
    assert (trimmed["trim_start"], trimmed["trim_end"]) == (20.0, 26.5)  # far from the AI's pick
    assert trimmed["drink_text"] == "TAKE A SIP"  # kept through a re-trim
    new_preview = settings.changeover_dir / Path(trimmed["preview_url"]).name
    assert new_preview != old_preview and not old_preview.exists() and kept.exists()
    assert _probe(new_preview)[0] == pytest.approx(6.5 + fx.VIDEO_TAIL_SECONDS, abs=0.25)

    resp = client.post(f"/api/ai-transitions/{project_id}/{item['id']}/text", json={"drink_text": ""})
    assert resp.status_code == 202
    plain = _wait_idle(client, project_id, timeout=60)["transitions"][0]
    assert plain["status"] == "ready" and plain["drink_text"] == ""
    assert (plain["trim_start"], plain["trim_end"]) == (20.0, 26.5)

    too_short = client.post(f"/api/ai-transitions/{project_id}/{item['id']}/trim", json={"start": 7.0, "end": 7.2})
    assert too_short.status_code == 422

    assert client.delete(f"/api/ai-transitions/{project_id}/{item['id']}").status_code == 200
    assert not kept.exists()  # trashing removes the kept source too


def test_cards_cannot_be_trimmed(client, project_id, fake_builds):
    client.post(f"/api/ai-transitions/{project_id}/generate", json={"count": 1, "sources": "cards"})
    item = _wait_idle(client, project_id)["transitions"][0]
    assert item["source_url"] == ""
    resp = client.post(f"/api/ai-transitions/{project_id}/{item['id']}/trim", json={"start": 0, "end": 2})
    assert resp.status_code == 409


def test_style_column_is_added_to_an_existing_table():
    from sqlalchemy import create_engine, text

    from app.core.migrations import add_missing_columns

    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE changover_clips (id INTEGER PRIMARY KEY, origin TEXT)"))
        add_missing_columns(conn)
        add_missing_columns(conn)  # idempotent
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(changover_clips)"))}
    assert "style" in columns
