"""Proposal speed: clean clip queries, parallel searches, and review fallbacks before re-planning."""

import asyncio
import json
from types import SimpleNamespace

from app.models.schemas import SearchResult
from app.services import auto_generate as ag


def _result(vid, title, artist="chan"):
    return SearchResult(youtube_id=vid, title=title, artist=artist, thumbnail="",
                        duration="3:00", search_source="youtube_api")


class _AI:
    """Planner returns numbered Idol clips with a query; review rejects 'X Factor' titles."""

    def __init__(self):
        self.plans = 0
        self.reviews = 0
        self.counter = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        system = kwargs["messages"][0]["content"]
        if system == ag.REVIEW_SYSTEM_PROMPT:
            self.reviews += 1
            listing = kwargs["messages"][1]["content"].split("Results:\n", 1)[1].splitlines()
            body = {"reject": [i + 1 for i, line in enumerate(listing) if "X Factor" in line]}
        else:
            self.plans += 1
            tracks = []
            for _ in range(80):
                self.counter += 1
                n = self.counter
                tracks.append({
                    "title": f"Idol moment {n}",
                    "artist": "compilation / fan channel",
                    "query": f'"Idol moment {n}" — (audition)',
                })
            body = {"tracks": tracks}
        msg = SimpleNamespace(content=json.dumps(body))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def test_clean_query_strips_labels_and_punctuation():
    assert ag._clean_query('"William Hung" — She Bangs (audition) / [S3]') == "William Hung She Bangs audition S3"
    assert ag._clean_query(None) == ""


def test_clips_search_with_the_planner_query_songs_with_artist_title():
    clip = ag.PlannedSong(title="She Bangs audition", artist="(audition clip)", kind="clip",
                          query="William Hung She Bangs American Idol")
    assert ag._search_query(clip) == "William Hung She Bangs American Idol"
    song = ag.PlannedSong(title="A Moment Like This", artist="Kelly Clarkson", kind="song", query="ignored")
    assert ag._search_query(song) == "Kelly Clarkson - A Moment Like This"
    bare = ag.PlannedSong(title="She Bangs", artist="William Hung", kind="clip")
    assert ag._search_query(bare) == "William Hung - She Bangs"


def test_planner_query_is_cleaned_and_only_kept_for_clips():
    raw = [{"title": "t1", "artist": "a", "query": '"x" — y', "kind": "clip"},
           {"title": "t2", "artist": "b", "query": "z", "kind": "song"}]
    clip, song = ag._dedupe_planned_songs(raw, "mixed")
    assert clip.query == "x y" and song.query == ""


def test_rejected_slots_use_their_next_search_result_without_replanning(monkeypatch):
    ai = _AI()
    queries = []

    async def fake_search(query, max_results=10, preferred_artists=None, music=True):
        queries.append(query)
        n = query.split()[2]
        # Every other search's top hit is the wrong show; the runner-up is the right one.
        first = (_result(f"x{n}", f"X Factor moment {n}") if int(n) % 2 == 0
                 else _result(f"i{n}", f"Idol moment {n}"))
        return [first, _result(f"j{n}", f"Idol moment {n} full")]

    monkeypatch.setattr(ag, "_get_openai_client", lambda: ai)
    monkeypatch.setattr(ag, "search_youtube", fake_search)
    items = asyncio.run(ag._build_resolved_items("American Idol golden age", "videos"))

    resolved = [i for i in items if i.status == "resolved"]
    assert len(resolved) == ag.PROPOSAL_SIZE
    assert not any("X Factor" in i.title for i in resolved)
    assert ai.plans == 1  # fallbacks filled the rejected slots, no second planning round
    assert ai.reviews == 2
    assert all(q.startswith("Idol moment ") and '"' not in q for q in queries)


def test_searches_run_in_parallel_but_capped(monkeypatch):
    ai = _AI()
    in_flight = 0
    peak = 0

    async def slow_search(query, max_results=10, preferred_artists=None, music=True):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.005)
        in_flight -= 1
        n = query.split()[2]
        return [_result(f"i{n}", f"Idol moment {n}")]

    monkeypatch.setattr(ag, "_get_openai_client", lambda: ai)
    monkeypatch.setattr(ag, "search_youtube", slow_search)
    items = asyncio.run(ag._build_resolved_items("American Idol golden age", "videos"))
    assert sum(i.status == "resolved" for i in items) == ag.PROPOSAL_SIZE
    assert 1 < peak <= ag.SEARCH_CONCURRENCY
    # Resolved in plan order: the first slots are the planner's first ideas.
    assert sorted(int(i.requested_title.split()[-1]) for i in items)[:5] == [1, 2, 3, 4, 5]
