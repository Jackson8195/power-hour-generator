"""Compilation videos: one long non-music video fills several AI slots, downloaded once."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models.schemas import AutoGenerateProposalItem, SearchResult
from app.services import auto_generate as ag


def _result(vid, duration):
    return SearchResult(youtube_id=vid, title=vid, artist="chan", thumbnail="", duration=duration,
                        search_source="youtube_api")


def test_duration_parsing():
    assert ag._duration_seconds("4:33") == 273
    assert ag._duration_seconds("1:02:03") == 3723
    assert ag._duration_seconds("") is None
    assert ag._duration_seconds("LIVE") is None


def test_single_clip_slots_skip_long_uploads():
    long, short = _result("long", "45:00"), _result("short", "4:00")
    assert ag._pick_clip_source([long, short], 1) == (short, 1)


def test_only_a_long_match_is_used_for_a_few_parts_not_one():
    result, parts = ag._pick_clip_source([_result("long", "45:00")], 1)
    assert result.youtube_id == "long" and parts == ag.FALLBACK_LONG_SEGMENTS


def test_compilation_parts_are_capped_by_runtime_and_limit():
    # 5 minutes of footage only supports 3 parts at 90s each, even if the AI asked for 5.
    assert ag._pick_clip_source([_result("c", "5:00")], 5)[1] == 3
    assert ag._pick_clip_source([_result("c", "40:00")], 99)[1] == ag.MAX_COMPILATION_SEGMENTS
    # too short to split: falls back to a single clip
    assert ag._pick_clip_source([_result("c", "2:30")], 4)[1] == 1


def test_never_picks_sources_over_the_download_cap():
    assert ag._pick_clip_source([_result("huge", "10:00:00")], 3) == (None, 1)


def test_segments_are_only_read_for_clips():
    raw = [{"title": "Comp", "artist": "a", "kind": "clip", "segments": 4},
           {"title": "Song", "artist": "b", "kind": "song", "segments": 4},
           {"title": "Junk", "artist": "c", "kind": "clip", "segments": "lots"}]
    assert [s.segments for s in ag._dedupe_planned_songs(raw, "mixed")] == [4, 1, 1]


def test_group_by_source_keeps_first_appearance_order():
    pairs = [(1, "a"), (2, "b"), (3, "a"), (4, ""), (5, "b")]
    assert ag._group_by_source(pairs) == [[1, 3], [2, 5], [4]]


def test_label_segments_numbers_shared_videos():
    def item(i, vid, status="resolved"):
        return AutoGenerateProposalItem(slot_index=i, requested_title=f"t{i}", requested_artist="",
                                        youtube_id=vid, status=status)

    labeled = ag._label_segments([item(0, "x"), item(1, "y"), item(2, "x"), item(3, "x", "unresolved")])
    assert [(i.segment_index, i.segment_count) for i in labeled] == [(0, 2), (0, 1), (1, 2), (0, 1)]


class _CompilationPlanner:
    """First call: one compilation (3 parts) + plain clips. Later calls: more plain clips."""

    def __init__(self):
        self.counter = 0
        self.prompts = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        tracks = []
        if self.counter == 0:
            tracks.append({"title": "Best Sketches Compilation", "artist": "Comedy Chan", "segments": 3})
        for _ in range(30):
            self.counter += 1
            tracks.append({"title": f"Bit {self.counter}", "artist": f"Creator {self.counter}"})
        msg = SimpleNamespace(content=json.dumps({"tracks": tracks}))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def test_compilation_fills_several_spread_out_slots(monkeypatch):
    planner = _CompilationPlanner()

    async def fake_search(query, max_results=10, preferred_artists=None, music=True):
        duration = "30:00" if "Compilation" in query else "3:00"
        return [_result(f"id-{query}", duration)]

    monkeypatch.setattr(ag, "_get_openai_client", lambda: planner)
    monkeypatch.setattr(ag, "search_youtube", fake_search)

    items = asyncio.run(ag._build_resolved_items("comedy", "videos"))
    assert len(items) == ag.PROPOSAL_SIZE
    comp = [i for i in items if "Compilation" in i.requested_title]
    assert len(comp) == 3 and len({i.youtube_id for i in comp}) == 1
    assert sorted(i.segment_index for i in comp) == [0, 1, 2] and all(i.segment_count == 3 for i in comp)
    positions = [i.slot_index for i in comp]
    assert all(b - a > 1 for a, b in zip(positions, positions[1:]))  # never back to back
    assert '"segments"' in planner.prompts[0]


def test_one_download_feeds_every_part(monkeypatch, make_clip, db):
    """The AI build downloads a compilation once and saves each part's range for review:
    nothing is trimmed, and the shared source stays for the review screen."""
    clip_ids = [make_clip("comp1", position=i) for i in range(3)]
    downloads, deleted = [], []
    source = settings.downloads_dir / "comp1_src.mp4"

    async def fake_download(youtube_id, file_stem=None, **_):
        downloads.append(youtube_id)
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"x")
        return {"file_path": str(source), "title": "Comp", "artist": "Chan"}

    async def fake_analyze(path, clip_duration=60, segment_count=1):
        assert segment_count == 3
        return {"waveform": [0.5], "duration": 1800.0, "bpm": None, "energy": 0.2,
                "suggested_start": 100.0, "suggested_end": 160.0, "highlights": [],
                # only two distinct parts found: the third clip must error, not reuse footage
                "segments": [{"start": 100.0, "end": 160.0}, {"start": 900.0, "end": 958.0}]}

    monkeypatch.setattr(ag, "download_video", fake_download)
    monkeypatch.setattr(ag, "analyze_audio", fake_analyze)
    monkeypatch.setattr(ag, "unlink_managed_file", lambda p, root: deleted.append(p))

    job = asyncio.run(ag.create_auto_generate_job(1, 3))
    ready = asyncio.run(ag.auto_process_source(clip_ids, job.job_id, 0, 3))

    assert ready == 2 and downloads == ["comp1"]
    assert deleted == []  # kept for review
    rows = {r["id"]: r for r in db.execute(
        f"SELECT id, status, file_path, start_time, end_time, duration, error_message FROM clips "
        f"WHERE id IN ({','.join('?' * 3)})", clip_ids)}
    assert [rows[c]["status"] for c in clip_ids] == ["READY", "READY", "ERROR"]
    # Both parts point at the one full source with their own draft range.
    assert rows[clip_ids[0]]["file_path"] == rows[clip_ids[1]]["file_path"] == str(source)
    assert (rows[clip_ids[0]]["start_time"], rows[clip_ids[0]]["end_time"]) == (100.0, 160.0)
    assert (rows[clip_ids[1]]["start_time"], rows[clip_ids[1]]["end_time"]) == (900.0, 958.0)
    assert rows[clip_ids[1]]["duration"] == pytest.approx(1800.0)  # the source's length
    assert rows[clip_ids[2]]["error_message"] == ag.NOT_ENOUGH_FOOTAGE_MESSAGE
    # Each part's review screen recommends its own range.
    from app.api.clip_utils import load_clip_analysis
    assert load_clip_analysis(clip_ids[1])["suggested_start"] == 900.0


def test_shared_source_survives_until_the_last_part_is_trimmed(client, make_clip, monkeypatch):
    """Trimming or deleting one compilation part must not delete the source the others use."""
    import app.api.clips as clips_api

    source = settings.downloads_dir / "shared_src.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"x")
    first, second, third = (
        make_clip("shared", file_path=str(source), duration=1800.0, status="READY",
                  start_time=start, end_time=start + 60.0)
        for start in (100.0, 500.0, 900.0)
    )

    async def fake_extract(source_path, output_path, start_time, end_time):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"clip")

    monkeypatch.setattr(clips_api, "extract_clip_segment", fake_extract)
    assert client.post(f"/api/clips/{first}/commit", json={"start_time": 100, "end_time": 160}).status_code == 200
    assert source.exists()
    assert client.delete(f"/api/clips/{second}").status_code == 200
    assert source.exists()
    assert client.post(f"/api/clips/{third}/commit", json={"start_time": 900, "end_time": 960}).status_code == 200
    assert not source.exists()  # the last user is gone


def test_build_stops_for_review_instead_of_rendering(monkeypatch, make_clip, db):
    """Every AI build ends in the "review" phase: nothing is rendered automatically."""
    clip_ids = [make_clip(f"v{i}", position=i) for i in range(3)]

    async def fake_process(clip_ids, job_id, first_index, total_clips):
        return len(clip_ids)

    monkeypatch.setattr(ag, "auto_process_source", fake_process)
    job = asyncio.run(ag.create_auto_generate_job(1, 3))

    async def run():
        await ag.start_auto_process_queue(job.job_id, 1, clip_ids)
        return await ag.job_store.get(job.job_id)

    done = asyncio.run(run())
    assert done.phase == "review" and done.render_id is None
    assert done.current_step == "Ready for your review"
    assert db.execute("SELECT COUNT(*) FROM renders").fetchone()[0] == 0
    # a build waiting for review is not "running": no device offers to resume it
    active = asyncio.run(ag.job_store.active())
    assert active is None or active.job_id != job.job_id
