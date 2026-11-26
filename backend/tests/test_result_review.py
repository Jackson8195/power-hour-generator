"""Off-prompt YouTube results are filtered: a keyword check, then an AI review of real titles."""

import asyncio
import json
from types import SimpleNamespace

from app.models.schemas import AutoGenerateProposalItem, SearchResult
from app.services import auto_generate as ag


def _result(title, artist="chan"):
    return SearchResult(youtube_id=title, title=title, artist=artist, thumbnail="",
                        duration="3:00", search_source="youtube_api")


def test_clip_results_must_share_words_with_the_request():
    query = "American Idol - William Hung She Bangs audition"
    assert ag._shares_query_terms(_result("William Hung - She Bangs (American Idol)"), query)
    assert not ag._shares_query_terms(
        _result("Police bodycam video shows aftermath of deadly road rage shooting", "News 5"), query)


class _ReviewingAI:
    """Plans numbered clips; the review rejects anything whose title mentions X Factor."""

    def __init__(self, fail_review=False):
        self.counter = 0
        self.fail_review = fail_review
        self.reviews = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        system = kwargs["messages"][0]["content"]
        if system == ag.REVIEW_SYSTEM_PROMPT:
            self.reviews += 1
            if self.fail_review:
                raise RuntimeError("review down")
            listing = kwargs["messages"][1]["content"].split("Results:\n", 1)[1].splitlines()
            reject = [i + 1 for i, line in enumerate(listing) if "X Factor" in line]
            body = {"reject": reject}
        else:
            tracks = []
            for _ in range(20):
                self.counter += 1
                show = "X Factor" if self.counter % 5 == 0 else "American Idol"
                tracks.append({"title": f"{show} moment {self.counter}", "artist": f"c{self.counter}"})
            body = {"tracks": tracks}
        msg = SimpleNamespace(content=json.dumps(body))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _patch(monkeypatch, ai):
    async def fake_search(query, max_results=10, preferred_artists=None, music=True):
        return [_result(query.split(" - ", 1)[-1], "chan")]

    monkeypatch.setattr(ag, "_get_openai_client", lambda: ai)
    monkeypatch.setattr(ag, "search_youtube", fake_search)


def test_review_rejections_never_reach_the_proposal(monkeypatch):
    ai = _ReviewingAI()
    _patch(monkeypatch, ai)
    items = asyncio.run(ag._build_resolved_items("American Idol golden age", "videos"))
    resolved = [i for i in items if i.status == "resolved"]
    assert len(resolved) == ag.PROPOSAL_SIZE and ai.reviews >= 1
    assert not any("X Factor" in i.title for i in items)


def test_a_failing_review_keeps_results(monkeypatch):
    ai = _ReviewingAI(fail_review=True)
    _patch(monkeypatch, ai)
    items = asyncio.run(ag._build_resolved_items("American Idol golden age", "videos"))
    assert sum(i.status == "resolved" for i in items) == ag.PROPOSAL_SIZE


def test_replacement_skips_rejected_alternates(monkeypatch):
    ai = _ReviewingAI()
    _patch(monkeypatch, ai)

    async def alternates(**_):
        return [ag.PlannedSong(title="X Factor audition", artist="a", kind="clip"),
                ag.PlannedSong(title="American Idol audition", artist="b", kind="clip")]

    monkeypatch.setattr(ag, "_plan_replacements", alternates)
    original = AutoGenerateProposalItem(slot_index=0, requested_title="old", requested_artist="z",
                                        youtube_id="old", title="old", status="resolved", kind="clip")
    proposal = ag.StoredProposal(proposal_id="p", prompt="idol", normalized_prompt="idol",
                                 items=[original], expires_at=None, mode="videos")
    replacement = asyncio.run(ag.replace_playlist_item(proposal, 0))
    assert replacement.status == "resolved" and replacement.title == "American Idol audition"
