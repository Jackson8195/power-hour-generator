"""AI-created transitions: migration, sanitizing, ffmpeg safety, cycling, and fallbacks."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.core.database import async_session
from app.core.migrations import migrate_changeover_table
from app.models.schemas import AutoGenerateProposalApproveRequest, ChangoverClipDB
from app.services import ai_transitions as ait
from app.services import ffmpeg
from app.services.changeover import apply_changeover_interleave

LEGACY_DDL = """
CREATE TABLE changover_clips (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL UNIQUE,
    source_type VARCHAR(20), youtube_id VARCHAR(50), image_path VARCHAR(500),
    audio_path VARCHAR(500), raw_video_path VARCHAR(500), output_path VARCHAR(500),
    duration FLOAT, trim_start FLOAT, trim_end FLOAT, status VARCHAR(50),
    error_message TEXT, created_at DATETIME, updated_at DATETIME
)
"""


# ─── migration ───────────────────────────────────────────

def test_migration_keeps_rows_and_allows_several_per_project():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(LEGACY_DDL))
        conn.execute(text(
            "INSERT INTO changover_clips (project_id, source_type, output_path, duration, status, error_message) "
            "VALUES (7, 'youtube', '/m/changeover/x.mp4', 3.5, 'ready', '')"
        ))
        # the old schema really did forbid a second row for the project
        with pytest.raises(Exception):
            conn.execute(text("INSERT INTO changover_clips (project_id) VALUES (7)"))

    with engine.begin() as conn:
        migrate_changeover_table(conn)
        row = conn.execute(text(
            "SELECT project_id, origin, position, label, source_type, output_path, duration, status "
            "FROM changover_clips"
        )).one()
        assert tuple(row) == (7, "manual", 0, "", "youtube", "/m/changeover/x.mp4", 3.5, "ready")
        conn.execute(text("INSERT INTO changover_clips (project_id, origin, position) VALUES (7, 'ai', 1)"))
        conn.execute(text("INSERT INTO changover_clips (project_id, origin, position) VALUES (7, 'ai', 2)"))
        assert conn.execute(text("SELECT COUNT(*) FROM changover_clips WHERE project_id = 7")).scalar() == 3
        # legacy table is gone and a second run is a no-op
        assert "changover_clips_legacy" not in {
            r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
        migrate_changeover_table(conn)
        assert conn.execute(text("SELECT COUNT(*) FROM changover_clips")).scalar() == 3


def test_migration_is_a_noop_without_a_table():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        migrate_changeover_table(conn)  # must not raise or create anything
        assert conn.execute(text("SELECT name FROM sqlite_master")).first() is None


# ─── sanitizing untrusted AI output ──────────────────────

def test_spec_text_is_cleaned_and_limited():
    spec = ait.sanitize_spec(
        {"headline": "  A very very long headline that keeps going \n\t", "subline": "x" * 100,
         "countdown": ["3", "2", "1", "extra", "x" * 50], "label": "L" * 200}, "cards")
    assert spec.headline == "A very very long h"  # whitespace collapsed, cut at 18 chars
    assert len(spec.subline) == 32 and len(spec.label) == 60
    assert spec.countdown == ["3", "2", "1"]


def test_colors_come_only_from_the_palette():
    spec = ait.sanitize_spec({"text_color": "red; rm -rf /", "bg_color": "#123456"}, "cards")
    assert spec.text_color == ait.PALETTE["yellow"] and spec.bg_color == ait.PALETTE["black"]
    same = ait.sanitize_spec({"text_color": "white", "bg_color": "white"}, "cards")
    assert same.text_color != same.bg_color


def test_duration_is_clamped_and_bad_values_default():
    assert ait.sanitize_spec({"duration": 99}, "cards").duration == 6.0
    assert ait.sanitize_spec({"duration": 0.1}, "cards").duration == 3.0
    assert ait.sanitize_spec({"duration": "soon"}, "cards").duration == 4.0


def test_sources_force_the_kind_and_youtube_needs_a_query():
    raw = [{"kind": "youtube", "query": "airhorn"}, {"kind": "card", "headline": "GO"}]
    assert {s.kind for s in ait.sanitize_specs(raw, 5, "cards")} == {"card"}
    forced = ait.sanitize_specs(raw, 5, "youtube")
    assert {s.kind for s in forced} == {"youtube"} and all(s.query for s in forced)
    assert {s.kind for s in ait.sanitize_specs(raw, 5, "both")} == {"youtube", "card"}


def test_specs_are_deduped_and_capped():
    raw = [{"headline": "SHOT"}, {"headline": "shot"}, {"headline": "DRINK"}, {"headline": "CHEERS"}]
    assert [s.headline for s in ait.sanitize_specs(raw, 2, "cards")] == ["SHOT", "DRINK"]
    many = [{"headline": f"H{i}"} for i in range(30)]
    assert len(ait.sanitize_specs(many, 99, "cards")) == ait.MAX_COUNT
    assert ait.sanitize_specs("not a list", 3, "cards") == []
    assert ait.sanitize_specs([None, 5, "x"], 3, "cards") == []


def test_approve_request_bounds():
    ok = AutoGenerateProposalApproveRequest(ai_transition_count=8, ai_transition_sources="youtube")
    assert ok.ai_transition_count == 8
    with pytest.raises(Exception):
        AutoGenerateProposalApproveRequest(ai_transition_count=9)
    with pytest.raises(Exception):
        AutoGenerateProposalApproveRequest(ai_transition_sources="anything")
    assert AutoGenerateProposalApproveRequest().ai_transition_count == 0


# ─── ffmpeg: AI text never enters the filter string ──────

def test_text_card_passes_text_via_files_not_the_filter(monkeypatch, tmp_path):
    captured = {}

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_exec(*cmd, **_):
        captured["cmd"] = list(cmd)
        # the text files must exist while ffmpeg would read them
        vf = cmd[cmd.index("-vf") + 1]
        for part in vf.split(","):
            if "textfile=" in part:
                path = part.split("textfile=")[1].split(":")[0]
                captured.setdefault("texts", []).append(Path(path).read_text())
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    nasty = "A'B:%{pts}\\,;[x]"
    asyncio.run(ffmpeg.build_text_card(
        str(tmp_path / "c.mp4"), countdown=["3"], headline=nasty, subline="sub",
        text_color="#FFE600", bg_color="#000000", duration=4.0))

    vf = captured["cmd"][captured["cmd"].index("-vf") + 1]
    assert "expansion=none" in vf and "textfile=" in vf
    assert nasty not in " ".join(captured["cmd"])
    assert nasty in captured["texts"]


# ─── interleave cycling & manual API compatibility ───────

def _add_row(db, project_id, origin, position, path, label="", status="ready", duration=4.0):
    db.execute(
        "INSERT INTO changover_clips (project_id, origin, position, label, source_type, output_path, "
        "duration, status, error_message) VALUES (?, ?, ?, ?, 'ai_card', ?, ?, ?, '')",
        (project_id, origin, position, label, str(path), duration, status),
    )
    db.commit()


def test_interleave_cycles_through_transitions_in_position_order(client, project_id, db, media_file):
    a, b, c = (media_file("changeover", f"t{i}.mp4") for i in range(3))
    _add_row(db, project_id, "ai", 2, c, "C")
    _add_row(db, project_id, "ai", 0, a, "A")
    _add_row(db, project_id, "ai", 1, b, "B")
    songs = [{"file_path": f"/s{i}.mp4", "start_time": 0, "end_time": 60, "title": f"S{i}"} for i in range(6)]

    async def run():
        async with async_session() as session:
            return await apply_changeover_interleave(session, project_id, songs)

    out = client.portal.call(run)
    gaps = [c for c in out if c.get("is_changeover")]
    assert [g["title"] for g in gaps] == ["A", "B", "C", "A", "B"]
    assert len(out) == 6 + 5 and not out[-1].get("is_changeover")


def test_interleave_skips_missing_files_and_not_ready_rows(client, project_id, db, media_file):
    good = media_file("changeover", "good.mp4")
    _add_row(db, project_id, "ai", 0, "/nonexistent.mp4", "gone")
    _add_row(db, project_id, "ai", 1, good, "pending-one", status="pending")
    _add_row(db, project_id, "ai", 2, good, "OK")
    songs = [{"file_path": f"/s{i}.mp4", "start_time": 0, "end_time": 60, "title": "s"} for i in range(3)]

    async def run():
        async with async_session() as session:
            return await apply_changeover_interleave(session, project_id, songs)

    gaps = [c for c in client.portal.call(run) if c.get("is_changeover")]
    assert [g["title"] for g in gaps] == ["OK", "OK"]


def test_manual_api_ignores_ai_rows_and_project_delete_removes_all(client, project_id, db, media_file):
    f = media_file("changeover", "x.mp4")
    _add_row(db, project_id, "ai", 0, f, "A")
    _add_row(db, project_id, "ai", 1, f, "B")
    # only AI rows exist: the single-manual-transition endpoints must not crash on several rows
    assert client.get(f"/api/changeover/{project_id}").status_code == 404

    assert client.delete(f"/api/projects/{project_id}").status_code == 200
    assert db.execute("SELECT COUNT(*) FROM changover_clips WHERE project_id = ?", (project_id,)).fetchone()[0] == 0


# ─── creating them: fallbacks ────────────────────────────

def _specs(*pairs):
    return [ait.TransitionSpec(kind=k, label=l, headline=l.upper(), query=l) for k, l in pairs]


def _create(client, project_id, **kw):
    async def run():
        async with async_session() as session:
            return await ait.create_ai_transitions(session, project_id, "80s hits", **kw)

    return client.portal.call(run)


def test_failed_youtube_transition_falls_back_to_a_card(client, project_id, db, monkeypatch):
    built = []

    async def fake_plan(theme, count, sources):
        return _specs(("card", "shot"), ("youtube", "airhorn"), ("youtube", "rickroll"))

    async def fake_card(spec, output_path, resolution):
        built.append(("card", spec.label))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"x")

    async def fake_youtube(spec, project_id, index, output_path, resolution):
        if spec.query == "airhorn":
            raise RuntimeError("no results")
        built.append(("youtube", spec.label))
        Path(output_path).write_bytes(b"x")
        return "yt123"

    monkeypatch.setattr(ait, "plan_transitions", fake_plan)
    monkeypatch.setattr(ait, "_build_card", fake_card)
    monkeypatch.setattr(ait, "_build_youtube", fake_youtube)

    assert _create(client, project_id, count=3) == 3
    rows = db.execute(
        "SELECT position, origin, source_type, youtube_id, status, label FROM changover_clips "
        "WHERE project_id = ? ORDER BY position", (project_id,)).fetchall()
    assert [tuple(r) for r in rows] == [
        (0, "ai", "ai_card", "", "ready", "shot"),
        (1, "ai", "ai_card", "", "ready", "airhorn"),   # fell back to a card
        (2, "ai", "ai_youtube", "yt123", "ready", "rickroll"),
    ]
    assert built == [("card", "shot"), ("card", "airhorn"), ("youtube", "rickroll")]


def test_planning_failure_falls_back_to_default_cards_and_regeneration_replaces(client, project_id, db, monkeypatch):
    async def boom(theme, count, sources):
        raise RuntimeError("openai down")

    async def fake_card(spec, output_path, resolution):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"x")

    monkeypatch.setattr(ait, "plan_transitions", boom)
    monkeypatch.setattr(ait, "_build_card", fake_card)

    assert _create(client, project_id, count=3) == 3
    labels = {r[0] for r in db.execute("SELECT label FROM changover_clips WHERE project_id=?", (project_id,))}
    assert len(labels) == 3  # distinct cards, not three copies of one
    # running again replaces the AI rows instead of piling up
    assert _create(client, project_id, count=2) == 2
    assert db.execute("SELECT COUNT(*) FROM changover_clips WHERE project_id=?", (project_id,)).fetchone()[0] == 2


def test_if_nothing_builds_zero_is_returned(client, project_id, monkeypatch):
    async def fake_plan(theme, count, sources):
        return _specs(("card", "a"), ("card", "b"))

    async def broken_card(spec, output_path, resolution):
        raise RuntimeError("ffmpeg missing")

    monkeypatch.setattr(ait, "plan_transitions", fake_plan)
    monkeypatch.setattr(ait, "_build_card", broken_card)
    assert _create(client, project_id, count=2) == 0


def test_queue_step_falls_back_to_default_card_when_none_ready(client, project_id, monkeypatch):
    from app.services import auto_generate as ag
    from app.services import changeover as changeover_svc

    calls = []

    async def none_ready(db, pid, theme, count, sources):
        calls.append("ai")
        return 0

    async def default_card(db, pid, *a, **k):
        calls.append("default")

    monkeypatch.setattr(ait, "create_ai_transitions", none_ready)
    monkeypatch.setattr(changeover_svc, "ensure_default_changeover", default_card)

    async def run():
        j = await ag.create_auto_generate_job(project_id, 1)
        await ag._create_ai_transitions_step(j.job_id, project_id, ag.AiTransitionRequest("theme", 3))
        return await ag.job_store.get(j.job_id)

    state = client.portal.call(run)
    assert calls == ["ai", "default"]
    assert state.current_step == "Creating transition clips"
