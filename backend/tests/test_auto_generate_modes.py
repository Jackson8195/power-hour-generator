"""AI playlist generation: music / videos / mixed modes and per-slot kinds."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.models.schemas import AutoGenerateProposalCreate, AutoGenerateProposalItem, SearchResult
from app.services import auto_generate as ag


def test_legacy_music_flag_still_maps_to_a_mode():
    assert AutoGenerateProposalCreate(prompt="eighties hits").effective_mode == "music"
    assert AutoGenerateProposalCreate(prompt="eighties hits", music=False).effective_mode == "videos"
    assert AutoGenerateProposalCreate(prompt="x y z", mode="mixed", music=True).effective_mode == "mixed"


def test_invalid_mode_is_rejected(client):
    resp = client.post("/api/auto-generate/proposals", json={"prompt": "something", "mode": "bogus"})
    assert resp.status_code == 422


def test_planned_kind_follows_mode():
    raw = [{"title": "A", "artist": "x", "kind": "clip"}, {"title": "B", "artist": "y", "kind": "song"},
           {"title": "C", "artist": "z"}]
    assert [s.kind for s in ag._dedupe_planned_songs(raw, "music")] == ["song"] * 3
    assert [s.kind for s in ag._dedupe_planned_songs(raw, "videos")] == ["clip"] * 3
    # mixed trusts the AI's kind; a missing kind defaults to song
    assert [s.kind for s in ag._dedupe_planned_songs(raw, "mixed")] == ["clip", "song", "song"]


def test_slot_mode_keeps_each_slots_own_kind_in_mixed():
    assert ag._slot_mode("mixed", "clip") == "videos"
    assert ag._slot_mode("mixed", "song") == "music"
    assert ag._slot_mode("music", "clip") == "music"
    assert ag._slot_mode("videos", "song") == "videos"


class _FakePlanner:
    """Stands in for the OpenAI client: returns unique tracks, alternating song/clip."""

    def __init__(self):
        self.calls = 0
        self.system_prompts = []
        self.counter = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.calls += 1
        self.system_prompts.append(kwargs["messages"][0]["content"])
        tracks = []
        for _ in range(20):
            self.counter += 1
            tracks.append({
                "kind": "clip" if self.counter % 2 == 0 else "song",
                "title": f"Item {self.counter}",
                "artist": f"Artist {self.counter}",
                "reason": "r",
            })
        msg = SimpleNamespace(content=json.dumps({"tracks": tracks}))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


@pytest.fixture()
def fake_ai(monkeypatch):
    planner = _FakePlanner()
    searches = []

    async def fake_search(query, max_results=10, preferred_artists=None, music=True):
        searches.append({"query": query, "music": music})
        vid = f"vid{len(searches)}"
        return [SearchResult(youtube_id=vid, title=query, artist="", thumbnail="", duration="3:00",
                             search_source="youtube_api")]

    monkeypatch.setattr(ag, "_get_openai_client", lambda: planner)
    monkeypatch.setattr(ag, "search_youtube", fake_search)
    return SimpleNamespace(planner=planner, searches=searches)


def test_mixed_mode_resolves_each_item_its_own_way(fake_ai):
    items = asyncio.run(ag._build_resolved_items("movie quotes and 90s hits", "mixed"))
    resolved = [i for i in items if i.status == "resolved"]
    assert {i.kind for i in resolved} == {"song", "clip"}
    # every item was searched with the music setting matching its kind
    by_query = {s["query"]: s["music"] for s in fake_ai.searches}
    for item in resolved:
        query = f"{item.requested_artist} - {item.requested_title}"
        assert by_query[query] == (item.kind == "song")
    assert "mixes songs with ordinary YouTube clips" in fake_ai.planner.system_prompts[0]


@pytest.mark.parametrize("mode,kind,music_flag", [("music", "song", True), ("videos", "clip", False)])
def test_single_modes_ignore_the_ai_kind(fake_ai, mode, kind, music_flag):
    items = asyncio.run(ag._build_resolved_items("anything", mode))
    resolved = [i for i in items if i.status == "resolved"]
    assert resolved and all(i.kind == kind for i in resolved)
    assert all(s["music"] is music_flag for s in fake_ai.searches)


def test_replacing_a_mixed_slot_keeps_its_kind(fake_ai):
    def item(i, kind):
        return AutoGenerateProposalItem(
            slot_index=i, requested_title=f"T{i}", requested_artist=f"A{i}", youtube_id=f"id{i}",
            title=f"T{i}", artist=f"A{i}", status="resolved", kind=kind,
        )

    proposal = ag.StoredProposal(
        proposal_id="p", prompt="mix", normalized_prompt="mix",
        items=[item(0, "song"), item(1, "clip")], expires_at=None, mode="mixed",
    )
    replacement = asyncio.run(ag.replace_playlist_item(proposal, 1))
    assert replacement.kind == "clip"
    assert fake_ai.searches and all(s["music"] is False for s in fake_ai.searches)

    fake_ai.searches.clear()
    replacement = asyncio.run(ag.replace_playlist_item(proposal, 0))
    assert replacement.kind == "song"
    assert all(s["music"] is True for s in fake_ai.searches)
