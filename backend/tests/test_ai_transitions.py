"""AI-created transitions: migration, sanitizing, ffmpeg safety, style, cycling, and fallbacks."""

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.core.database import async_session
from app.core.migrations import migrate_changeover_table
from app.models.schemas import AutoGenerateProposalApproveRequest, SearchResult
from app.services import ai_transitions as ait
from app.services import ffmpeg
from app.services import transition_fx as fx
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
         "label": "L" * 200}, "cards")
    assert spec.headline == "A very very long h"  # whitespace collapsed, cut at 18 chars
    assert len(spec.subline) == 40 and len(spec.label) == 60


def test_colors_come_only_from_the_palette():
    spec = ait.sanitize_spec({"text_color": "red; rm -rf /", "bg_color": "#123456"}, "cards")
    assert spec.text_color == ait.PALETTE["yellow"] and spec.bg_color == ait.PALETTE["black"]
    same = ait.sanitize_spec({"text_color": "white", "bg_color": "white"}, "cards")
    assert same.text_color != same.bg_color


def test_sound_and_call_word_come_only_from_fixed_lists():
    spec = ait.sanitize_spec({"sound": "Clink", "hit_text": "bottoms up"}, "cards")
    assert spec.sound == "clink" and spec.hit_text == "BOTTOMS UP!"
    # the scrapped synth sounds can't come back through the AI
    assert ait.sanitize_spec({"sound": "horn"}, "cards").sound != "horn"
    bad = ait.sanitize_spec({"sound": "rm -rf", "hit_text": "'; drop"}, "cards", index=1)
    assert bad.sound in fx.SOUNDS and bad.hit_text in fx.HIT_WORDS
    # unset fields rotate so a batch still varies
    assert len({ait.sanitize_spec({}, "cards", index=i).sound for i in range(3)}) == 3


def test_sources_force_the_kind_and_youtube_needs_a_query():
    raw = [{"kind": "youtube", "query": "airhorn"}, {"kind": "card", "headline": "GO"}]
    assert {s.kind for s in ait.sanitize_specs(raw, 5, "cards")} == {"card"}
    forced = ait.sanitize_specs(raw, 5, "youtube")
    assert {s.kind for s in forced} == {"youtube"} and all(s.query for s in forced)
    assert {s.kind for s in ait.sanitize_specs(raw, 5, "both")} == {"youtube", "card"}


def test_both_alternates_video_and_card_whatever_the_ai_chose():
    # the AI leaned on cards (what happened in the American Idol run); "both" must still mix
    raw = [{"kind": "card", "headline": f"H{i}", "query": f"q{i}", "label": f"L{i}"} for i in range(5)]
    raw[2].pop("query")
    specs = ait.sanitize_specs(raw, 5, "both")
    assert [s.kind for s in specs] == ["youtube", "card", "youtube", "card", "youtube"]
    assert specs[2].query == "L2"  # a video slot without a query searches for its label


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

class _FakeProc:
    def __init__(self, stdout=b""):
        self.returncode = 0
        self._stdout = stdout

    async def communicate(self):
        return self._stdout, b""


def _capture_ffmpeg(monkeypatch):
    """Record each ffmpeg call plus the text files it would read from its working dir."""
    calls = []

    async def fake_exec(*cmd, **kw):
        cmd = list(cmd)
        if Path(cmd[0]).name.startswith("ffprobe"):
            return _FakeProc(b"1\n")  # "the source has an audio stream"
        cwd = Path(kw.get("cwd") or ".")
        texts = {p.name: p.read_text(encoding="utf-8") for p in cwd.glob("*.txt")}
        graph = cmd[cmd.index("-filter_complex") + 1]
        calls.append({"cmd": cmd, "graph": graph, "texts": texts, "cwd": kw.get("cwd")})
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return calls


def test_text_card_passes_text_via_files_not_the_filter(monkeypatch, tmp_path):
    calls = _capture_ffmpeg(monkeypatch)
    nasty = "A'B:%{pts}\\,;[x]"
    length = asyncio.run(ffmpeg.build_text_card(
        str(tmp_path / "c.mp4"), headline=nasty, subline="sub",
        text_color="#FFE600", bg_color="#000000"))

    call = calls[-1]
    assert call["cwd"]  # text files live in ffmpeg's working dir...
    assert "expansion=none" in call["graph"] and "textfile=headline.txt" in call["graph"]
    assert ":\\" not in call["graph"] and ":/" not in call["graph"]  # ...so no paths in the graph
    assert nasty not in " ".join(call["cmd"])
    assert call["texts"]["headline.txt"] == nasty and call["texts"]["subline.txt"] == "sub"
    assert length == fx.CARD_SECONDS


def test_card_has_corner_countdown_motion_and_a_sound(monkeypatch, tmp_path):
    calls = _capture_ffmpeg(monkeypatch)
    asyncio.run(ffmpeg.build_text_card(
        str(tmp_path / "c.mp4"), headline="GO", hit_text="CHUG!", sound="bell", resolution="640x360"))
    call = calls[-1]
    graph, cmd = call["graph"], call["cmd"]
    # corner countdown: 3, 2, 1 in the top-right, one per second
    assert [call["texts"][f"corner_{n}.txt"] for n in (3, 2, 1)] == ["3", "2", "1"]
    assert "textfile=corner_3.txt" in graph and "x='w-text_w-w*0.035" in graph
    # motion: sliding bars, shake crop, flash; and the call word from its file
    assert "overlay=x='mod(t*" in graph and "crop=640:360:x=" in graph and "color=white@0.85" in graph
    assert call["texts"]["hit.txt"] == "CHUG!"
    # an audio source is generated and mapped: the card is not silent
    assert "aevalsrc=" in graph and "anullsrc" not in graph
    maps = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-map"]
    assert maps == ["[v]", "[a]"]


def test_default_shot_card_uses_the_same_style(monkeypatch, tmp_path):
    calls = _capture_ffmpeg(monkeypatch)
    asyncio.run(ffmpeg.build_default_shot_card(str(tmp_path / "d.mp4"), resolution="854x480"))
    call = calls[-1]
    assert call["texts"]["hit.txt"] == "SHOT!" and "aevalsrc=" in call["graph"]
    assert "textfile=corner_1.txt" in call["graph"] and "crop=854:480" in call["graph"]


def test_video_transition_appends_the_drink_cue(monkeypatch, tmp_path):
    calls = _capture_ffmpeg(monkeypatch)
    length = asyncio.run(fx.build_video_transition(
        str(tmp_path / "v.mp4"), str(tmp_path / "src.mp4"), start=12.0, clip_seconds=5.0,
        resolution="1920x1080", hit_text="DRINK!"))
    call = calls[-1]
    graph, cmd = call["graph"], call["cmd"]
    assert length == 5.0 + fx.VIDEO_TAIL_SECONDS
    assert cmd[cmd.index("-ss") + 1] == "12" and cmd[cmd.index("-t") + 1] == "5"
    assert cmd[len(cmd) - 1 - cmd[::-1].index("-t") + 1] == fx._f(length)  # output runs past the clip
    assert "tpad=stop_mode=clone" in graph  # freeze-frame beat after the clip
    assert "between(t,5,5.07)" in graph  # the call word punches in exactly when the clip ends
    assert call["texts"]["hit.txt"] == "DRINK!"
    # the cue (thump at the end, ticks over the last 3s, plus the recorded drink cue) is mixed
    # under the clip's audio
    assert "[0:a]" in graph and "afade=t=out" in graph and "amix=inputs=2" in graph
    assert fx.cue_expression(fx.DEFAULT_SOUND, 5.0, 2.0, riser=False) in graph
    assert "textfile=corner_3.txt" in graph and "between(t,2,2.1)" in graph  # countdown over 2..5s


def test_cue_expressions_put_the_thump_at_the_hit():
    """The generated layer is only the thump on the hit plus the countdown ticks; the drink cue
    itself is always a recording (no synthesized horn / buzzer / bell any more)."""
    expr = fx.cue_expression("can", 3.0, 0.0, riser=True)
    assert "between(t,3,3.8)" in expr  # thump at the hit
    assert "between(t,0,0.09)" in expr and "between(t,2,2.09)" in expr  # countdown ticks
    assert fx.cue_expression("nope", 3.0, None, riser=False) == fx.cue_expression("can", 3.0, None, riser=False)
    assert not hasattr(fx, "_horn") and not hasattr(fx, "_buzzer")


FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def _probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    return {s["codec_type"]: s for s in json.loads(out.stdout)["streams"]}


def _max_volume(path):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True)
    return float(out.stderr.split("max_volume:")[1].split("dB")[0])


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg not installed")
def test_real_card_and_video_transition_render_with_audible_audio(tmp_path):
    card = tmp_path / "card.mp4"
    length = asyncio.run(ffmpeg.build_text_card(
        str(card), headline="A'B:%{pts}", subline="q", resolution="320x180", sound="buzzer"))
    streams = _probe(card)
    assert (streams["video"]["width"], streams["video"]["height"]) == (320, 180)
    assert "audio" in streams and _max_volume(card) > -20
    assert length == fx.CARD_SECONDS

    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=25:d=8",
                    "-an", str(src)], check=True)  # no audio stream: the cue must still be there
    out = tmp_path / "v.mp4"
    asyncio.run(fx.build_video_transition(str(out), str(src), start=1.0, clip_seconds=4.0, resolution="320x180"))
    streams = _probe(out)
    assert (streams["video"]["width"], streams["video"]["height"]) == (320, 180)
    assert "audio" in streams and _max_volume(out) > -20


# ─── YouTube picks ───────────────────────────────────────

def _result(youtube_id, title, duration="0:30"):
    return SearchResult(youtube_id=youtube_id, title=title, thumbnail="", duration=duration)


def test_youtube_candidates_skip_playlist_videos_and_songs():
    playlist_titles = ["Kelly Clarkson - A Moment Like This (Official HD Video)"]
    results = [
        _result("FafDf2C0ZpM", "Kelly Clarkson - A Moment Like This"),  # in the playlist by id
        _result("other1", "A Moment Like This - Kelly Clarkson LIVE 2002 finale"),  # same song, other upload
        _result("long1", "Simon Cowell best insults compilation", "45:00"),  # too long to fetch
        _result("mid1", "Simon roasts contestants", "4:10"),
        _result("short1", "Simon: 'That was dreadful'", "0:12"),
    ]
    picked = ait.choose_youtube_candidates(results, {"FafDf2C0ZpM"}, playlist_titles)
    assert [r.youtube_id for r in picked] == ["short1", "mid1"]  # short first


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


# ─── creating them: fallbacks, reuse, mix ────────────────

def _specs(*pairs):
    return [ait.TransitionSpec(kind=k, label=l, headline=l.upper(), query=l) for k, l in pairs]


@pytest.fixture(autouse=True)
def _no_playlist(monkeypatch):
    async def empty(db, project_id):
        return set(), []

    monkeypatch.setattr(ait, "_playlist", empty)


def _create(client, project_id, **kw):
    async def run():
        async with async_session() as session:
            return await ait.create_ai_transitions(session, project_id, "80s hits", **kw)

    return client.portal.call(run)


async def _fake_card(spec, output_path, resolution):
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_bytes(b"x")
    return fx.CARD_SECONDS


def test_failed_youtube_transition_falls_back_to_a_card(client, project_id, db, monkeypatch):
    built = []

    async def fake_plan(theme, count, sources, avoid_titles=None, **kw):
        return _specs(("card", "shot"), ("youtube", "airhorn"), ("youtube", "rickroll"))

    async def fake_card(spec, output_path, resolution):
        built.append(("card", spec.label))
        return await _fake_card(spec, output_path, resolution)

    async def fake_youtube(spec, project_id, index, output_path, resolution, exclude_ids, playlist_titles):
        if spec.query == "airhorn":
            raise RuntimeError("no results")
        built.append(("youtube", spec.label))
        Path(output_path).write_bytes(b"x")
        return "yt123", 6.8

    monkeypatch.setattr(ait, "plan_transitions", fake_plan)
    monkeypatch.setattr(ait, "_build_card", fake_card)
    monkeypatch.setattr(ait, "_build_youtube", fake_youtube)

    assert _create(client, project_id, count=3) == 3
    rows = db.execute(
        "SELECT position, origin, source_type, youtube_id, status, label, duration FROM changover_clips "
        "WHERE project_id = ? ORDER BY position", (project_id,)).fetchall()
    assert [tuple(r) for r in rows] == [
        (0, "ai", "ai_card", "", "ready", "shot", 5.5),
        (1, "ai", "ai_card", "", "ready", "airhorn", 5.5),   # fell back to a card
        (2, "ai", "ai_youtube", "yt123", "ready", "rickroll", 6.8),  # real built length kept
    ]
    assert built == [("card", "shot"), ("card", "airhorn"), ("youtube", "rickroll")]


def test_youtube_picks_never_reuse_playlist_or_earlier_videos(client, project_id, monkeypatch):
    seen = []

    async def playlist(db, pid):
        return {"SONG1", "SONG2"}, ["Kelly Clarkson - A Moment Like This"]

    async def fake_plan(theme, count, sources, avoid_titles=None, **kw):
        seen.append(("avoid", list(avoid_titles or [])))
        return ait.sanitize_specs([{"headline": f"H{i}", "query": f"q{i}"} for i in range(4)], count, sources)

    async def fake_youtube(spec, project_id, index, output_path, resolution, exclude_ids, playlist_titles):
        seen.append(("exclude", set(exclude_ids)))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"x")
        return f"T{index}", 6.8

    monkeypatch.setattr(ait, "_playlist", playlist)
    monkeypatch.setattr(ait, "plan_transitions", fake_plan)
    monkeypatch.setattr(ait, "_build_youtube", fake_youtube)
    monkeypatch.setattr(ait, "_build_card", _fake_card)

    assert _create(client, project_id, count=4, sources="both") == 4
    assert seen[0] == ("avoid", ["Kelly Clarkson - A Moment Like This"])  # the AI is told the songs
    excludes = [e for kind, e in seen if kind == "exclude"]
    assert excludes == [{"SONG1", "SONG2"}, {"SONG1", "SONG2", "T0"}]  # slots 0 and 2 are videos


def test_both_produces_a_real_mix(client, project_id, db, monkeypatch):
    async def fake_plan(theme, count, sources, avoid_titles=None, **kw):
        # the AI marked everything a card, as in the bad run
        return ait.sanitize_specs(
            [{"kind": "card", "headline": f"H{i}", "query": f"q{i}"} for i in range(5)], count, sources)

    async def fake_youtube(spec, project_id, index, output_path, resolution, exclude_ids, playlist_titles):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"x")
        return f"vid{index}", 6.8

    monkeypatch.setattr(ait, "plan_transitions", fake_plan)
    monkeypatch.setattr(ait, "_build_youtube", fake_youtube)
    monkeypatch.setattr(ait, "_build_card", _fake_card)

    assert _create(client, project_id, count=5, sources="both") == 5
    kinds = [r[0] for r in db.execute(
        "SELECT source_type FROM changover_clips WHERE project_id = ? ORDER BY position", (project_id,))]
    assert kinds == ["ai_youtube", "ai_card", "ai_youtube", "ai_card", "ai_youtube"]


def test_transitions_follow_the_render_resolution(client, project_id, monkeypatch):
    from app.models.schemas import RenderRequest

    sizes = []

    async def fake_plan(theme, count, sources, avoid_titles=None, **kw):
        return _specs(("card", "a"))

    async def fake_card(spec, output_path, resolution):
        sizes.append(resolution)
        return await _fake_card(spec, output_path, resolution)

    monkeypatch.setattr(ait, "plan_transitions", fake_plan)
    monkeypatch.setattr(ait, "_build_card", fake_card)
    monkeypatch.setattr(RenderRequest.model_fields["resolution"], "default", "1920x1080")
    _create(client, project_id, count=1)
    assert sizes == ["1920x1080"]


def test_planning_failure_falls_back_to_default_cards_and_regeneration_replaces(client, project_id, db, monkeypatch):
    async def boom(theme, count, sources, avoid_titles=None, **kw):
        raise RuntimeError("openai down")

    monkeypatch.setattr(ait, "plan_transitions", boom)
    monkeypatch.setattr(ait, "_build_card", _fake_card)

    assert _create(client, project_id, count=3) == 3
    labels = {r[0] for r in db.execute("SELECT label FROM changover_clips WHERE project_id=?", (project_id,))}
    assert len(labels) == 3  # distinct cards, not three copies of one
    # running again replaces the AI rows instead of piling up
    assert _create(client, project_id, count=2) == 2
    assert db.execute("SELECT COUNT(*) FROM changover_clips WHERE project_id=?", (project_id,)).fetchone()[0] == 2


def test_if_nothing_builds_zero_is_returned(client, project_id, monkeypatch):
    async def fake_plan(theme, count, sources, avoid_titles=None, **kw):
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

    async def none_ready(db, pid, theme, count, sources, **_):
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
