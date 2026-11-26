"""AI-flow downloads ride out network outages, and a mostly-failed run isn't auto-rendered."""

import asyncio

import pytest

from app.services import auto_generate as ag

DNS_ERROR = (
    "yt-dlp failed: WARNING: [youtube] HTTPSConnection(host='www.youtube.com', port=443): "
    "Failed to resolve 'www.youtube.com' ([Errno -3] Temporary failure in name resolution)"
)


@pytest.fixture
def no_sleep(monkeypatch):
    waits = []

    async def fake_sleep(delay):
        waits.append(delay)

    monkeypatch.setattr(ag.asyncio, "sleep", fake_sleep)
    return waits


def test_dns_failure_is_a_network_error():
    assert ag._is_network_error(RuntimeError(DNS_ERROR))
    assert not ag._is_network_error(RuntimeError("yt-dlp failed: ERROR: Video unavailable"))


def test_download_retries_through_an_outage(monkeypatch, no_sleep):
    calls = []

    async def flaky_download(youtube_id, file_stem):
        calls.append(youtube_id)
        if len(calls) < 3:
            raise RuntimeError(DNS_ERROR)
        return {"file_path": "x.mp4"}

    monkeypatch.setattr(ag, "download_video", flaky_download)
    notices = []

    async def on_wait(delay):
        notices.append(delay)

    result = asyncio.run(ag._download_with_network_retry("abc", "abc_1", on_wait=on_wait))
    assert result == {"file_path": "x.mp4"}
    assert len(calls) == 3
    assert no_sleep == list(ag.NETWORK_RETRY_DELAYS[:2]) == notices


def test_non_network_errors_fail_immediately(monkeypatch, no_sleep):
    async def gone(youtube_id, file_stem):
        raise RuntimeError("yt-dlp failed: ERROR: Video unavailable")

    monkeypatch.setattr(ag, "download_video", gone)
    with pytest.raises(RuntimeError, match="unavailable"):
        asyncio.run(ag._download_with_network_retry("abc", "abc_1"))
    assert no_sleep == []


def test_gives_up_after_the_last_retry(monkeypatch, no_sleep):
    async def down(youtube_id, file_stem):
        raise RuntimeError(DNS_ERROR)

    monkeypatch.setattr(ag, "download_video", down)
    with pytest.raises(RuntimeError, match="name resolution"):
        asyncio.run(ag._download_with_network_retry("abc", "abc_1"))
    assert no_sleep == list(ag.NETWORK_RETRY_DELAYS)


def test_render_needs_most_of_the_playlist():
    assert ag._enough_ready_to_render(60, 60)
    assert ag._enough_ready_to_render(48, 60)
    assert not ag._enough_ready_to_render(17, 60)
    assert not ag._enough_ready_to_render(0, 0)
