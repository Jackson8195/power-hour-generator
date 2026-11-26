"""YouTube search: the music flag reaches yt-dlp whether or not an API key is configured."""

import asyncio

import pytest

from app.services import youtube


@pytest.mark.parametrize("music", [True, False])
def test_ytdlp_search_without_api_key_respects_music_flag(monkeypatch, music):
    calls = []

    async def fake_ytdlp(query, max_results, music=True):
        calls.append(music)
        return []

    monkeypatch.setattr(youtube.settings, "youtube_api_key", "")
    monkeypatch.setattr(youtube, "_search_with_ytdlp", fake_ytdlp)
    asyncio.run(youtube.search_youtube("funny moments", music=music))
    assert calls == [music]


def test_non_music_query_is_used_verbatim():
    assert youtube._build_search_query("funny moments", music=False) == "funny moments"
    assert youtube._build_search_query("Toto - Africa", music=True) == "Toto - Africa official music video"
