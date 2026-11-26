"""Revising an AI playlist without redoing the prompt: REVISE comments, locks, steered swaps, undo."""

import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.schemas import AutoGenerateProposalItem, SearchResult
from app.services import auto_generate as ag
from app.services.youtube import parse_youtube_id


def _item(i, title=None, kind="clip", locked=False):
    title = title or f"Idol moment {i}"
    return AutoGenerateProposalItem(
        slot_index=i, requested_title=title, requested_artist=f"c{i}", youtube_id=f"id{i}",
        title=title, artist=f"c{i}", duration="4:00", status="resolved", kind=kind, locked=locked,
    )


def _proposal(n=6, mode="videos", locked=()):
    return ag.StoredProposal(
        proposal_id="rev", prompt="american idol", normalized_prompt="american idol",
        items=[_item(i, locked=i in locked) for i in range(n)],
        expires_at=datetime.utcnow() + timedelta(hours=1), mode=mode,
    )


class _FakeAI:
    """Answers the REVISE planner with ``changes``, the swap planner with ``alternates``, and the
    review by rejecting titles containing ``reject``. Records every prompt it sees."""

    def __init__(self, changes=(), alternates=None, exact=False, reject="X Factor"):
        self.changes = list(changes)
        self.alternates = alternates or [{"title": "Funny swap", "artist": "s"}]
        self.exact = exact
        self.reject = reject
        self.prompts: list[tuple[str, str]] = []
        self.reviews = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        system, user = kwargs["messages"][0]["content"], kwargs["messages"][1]["content"]
        self.prompts.append((system, user))
        if system == ag.REVIEW_SYSTEM_PROMPT:
            self.reviews += 1
            listing = user.split("Results:\n", 1)[1].splitlines()
            body = {"reject": [i + 1 for i, line in enumerate(listing) if self.reject.lower() in line.lower()]}
        elif system.startswith(ag.REVISE_SYSTEM_PROMPT):
            body = {"changes": self.changes}
        else:
            body = {"tracks": self.alternates, "exact": self.exact}
        msg = SimpleNamespace(content=json.dumps(body))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


@pytest.fixture()
def fake(monkeypatch):
    holder = {}

    def install(ai, durations=None):
        async def search(query, max_results=10, preferred_artists=None, music=True):
            title = query.split(" - ", 1)[-1]
            return [SearchResult(youtube_id=f"yt-{title}", title=title, artist="chan", thumbnail="",
                                 duration=(durations or {}).get(title, "4:00"), search_source="youtube_api")]

        monkeypatch.setattr(ag, "_get_openai_client", lambda: ai)
        monkeypatch.setattr(ag, "search_youtube", search)
        holder["ai"] = ai
        return ai

    return install


def test_revise_swaps_only_the_slots_the_comment_calls_for(fake):
    ai = fake(_FakeAI(changes=[
        {"slots": [2], "kind": "clip", "title": "William Hung She Bangs", "query": "william hung she bangs"},
        {"slots": [5], "kind": "clip", "title": "Simon roasts singer", "query": "simon roasts singer"},
    ]))
    proposal = _proposal()
    changes = asyncio.run(ag.revise_playlist(proposal, "more funny auditions"))
    assert set(changes) == {1, 4}
    assert changes[1].requested_title == "William Hung She Bangs" and changes[1].slot_index == 1
    assert ai.reviews == 1 and "more funny auditions" in ai.prompts[-1][1]


def test_revise_never_touches_locked_slots_and_keeps_the_length(fake):
    fake(_FakeAI(changes=[
        {"slots": [1], "kind": "clip", "title": "Locked swap", "query": "locked swap"},
        {"slots": [3, 3, 99], "kind": "clip", "title": "Ok swap", "query": "ok swap"},
    ]))
    proposal = _proposal(locked={0})
    changes = asyncio.run(ag.revise_playlist(proposal, "change things"))
    assert set(changes) == {2}

    asyncio.run(ag.proposal_store.save(proposal))
    updated = asyncio.run(ag.proposal_store.apply_revision("rev", {**changes, 0: _item(0, "sneaky")}, "change things"))
    assert len(updated.items) == 6
    assert updated.items[0].title == "Idol moment 0" and updated.items[0].locked
    assert [item.revised for item in updated.items] == [False, False, True, False, False, False]
    assert updated.notes == ["change things"] and updated.undo is not None


def test_revise_can_cut_a_compilation_into_several_slots(fake):
    fake(_FakeAI(changes=[
        {"slots": [2, 4, 6], "kind": "clip", "title": "Funniest Idol auditions", "query": "funniest idol auditions"},
    ]), durations={"funniest idol auditions": "30:00"})
    proposal = _proposal()
    changes = asyncio.run(ag.revise_playlist(proposal, "use a compilation of funny auditions"))
    assert set(changes) == {1, 3, 5}
    assert {item.youtube_id for item in changes.values()} == {"yt-funniest idol auditions"}

    asyncio.run(ag.proposal_store.save(proposal))
    updated = asyncio.run(ag.proposal_store.apply_revision("rev", changes, "use a compilation"))
    parts = [item for item in updated.items if item.youtube_id == "yt-funniest idol auditions"]
    assert [p.segment_index for p in parts] == [0, 1, 2] and all(p.segment_count == 3 for p in parts)


def test_a_rejected_revision_entry_falls_back_to_a_steered_swap(fake):
    ai = fake(_FakeAI(
        changes=[{"slots": [3], "kind": "clip", "title": "X Factor fail", "query": "x factor fail"}],
        alternates=[{"title": "Idol blooper", "artist": "b", "query": "idol blooper"}],
    ))
    proposal = _proposal()
    changes = asyncio.run(ag.revise_playlist(proposal, "bloopers please"))
    assert changes[2].title == "idol blooper"
    # the fallback swap was steered by the new comment too
    swap_prompts = [user for system, user in ai.prompts if "Replace this song" in user]
    assert swap_prompts and "bloopers please" in swap_prompts[0]


def test_a_slot_with_no_usable_replacement_keeps_what_it_had(fake):
    fake(_FakeAI(
        changes=[{"slots": [3], "kind": "clip", "title": "X Factor fail", "query": "x factor fail"}],
        alternates=[{"title": "X Factor other", "artist": "b", "query": "x factor other"}],
    ))
    changes = asyncio.run(ag.revise_playlist(_proposal(), "something"))
    assert changes == {}


def test_undo_restores_the_list_and_notes_but_keeps_current_locks(fake):
    proposal = _proposal()
    asyncio.run(ag.proposal_store.save(proposal))
    asyncio.run(ag.proposal_store.apply_revision("rev", {1: _item(1, "new one")}, "first note"))
    asyncio.run(ag.proposal_store.set_locked("rev", 3, True))
    restored = asyncio.run(ag.proposal_store.undo_revision("rev"))
    assert restored.items[1].title == "Idol moment 1" and not any(i.revised for i in restored.items)
    assert restored.items[3].locked and restored.notes == [] and restored.undo is None
    assert asyncio.run(ag.proposal_store.undo_revision("rev")) is None


def test_comments_stick_for_later_swaps(fake):
    ai = fake(_FakeAI())
    proposal = _proposal()
    proposal.notes = ["no ballads"]
    asyncio.run(ag.replace_playlist_item(proposal, 0))
    planner = [user for system, user in ai.prompts if "Replace this song" in user][0]
    review = [user for system, user in ai.prompts if system == ag.REVIEW_SYSTEM_PROMPT][0]
    assert "no ballads" in planner and "no ballads" in review


def test_a_swap_note_steers_the_planner(fake):
    ai = fake(_FakeAI())
    asyncio.run(ag.replace_playlist_item(_proposal(), 0, note="something funnier"))
    planner = [user for system, user in ai.prompts if "Replace this song" in user][0]
    assert "something funnier" in planner and ai.reviews == 1


def test_an_exact_entry_skips_the_review(fake):
    ai = fake(_FakeAI(alternates=[{"title": "X Factor exact pick", "artist": "e"}], exact=True))
    item = asyncio.run(ag.replace_playlist_item(_proposal(), 0, note="X Factor exact pick"))
    assert item.status == "resolved" and item.requested_title == "X Factor exact pick"
    assert ai.reviews == 0


def test_a_youtube_link_is_used_as_is(fake, monkeypatch):
    ai = fake(_FakeAI())

    async def lookup(video_id):
        return SearchResult(youtube_id=video_id, title="My exact video", artist="me", thumbnail="t",
                            duration="3:10", search_source="youtube_api")

    monkeypatch.setattr(ag, "lookup_video", lookup)
    item = asyncio.run(ag.replace_playlist_item(_proposal(), 2, note="use https://youtu.be/dQw4w9WgXcQ?t=5"))
    assert item.youtube_id == "dQw4w9WgXcQ" and item.title == "My exact video" and item.slot_index == 2
    assert ai.prompts == []


def test_parse_youtube_id_forms():
    vid = "dQw4w9WgXcQ"
    for text in (f"https://www.youtube.com/watch?v={vid}", f"youtube.com/watch?feature=x&v={vid}",
                 f"https://youtu.be/{vid}", f"https://youtube.com/shorts/{vid}", f"m.youtube.com/embed/{vid}"):
        assert parse_youtube_id(text) == vid
    assert parse_youtube_id("Kelly Clarkson - Since U Been Gone") == ""


def test_api_lock_blocks_replace_and_undo_needs_a_revision(client):
    asyncio.run(ag.proposal_store.save(_proposal()))
    resp = client.post("/api/auto-generate/proposals/rev/lock", json={"slot_index": 1, "locked": True})
    assert resp.status_code == 200 and resp.json()["items"][1]["locked"] is True
    assert resp.json()["can_undo"] is False and resp.json()["notes"] == []
    resp = client.post("/api/auto-generate/proposals/rev/replace", json={"slot_index": 1, "note": "x"})
    assert resp.status_code == 409
    assert client.post("/api/auto-generate/proposals/rev/undo").status_code == 409
    assert client.post("/api/auto-generate/proposals/rev/revise", json={"comment": "  "}).status_code in (400, 422)
    assert client.post("/api/auto-generate/proposals/nope/revise", json={"comment": "more funny"}).status_code == 404
