"""Clips of the same YouTube video must not share a source file."""

import asyncio
from pathlib import Path

from app.services import youtube


class _FakeProc:
    returncode = 0

    async def communicate(self):
        return b'{"duration": 10, "title": "t", "channel": "c"}\n', b""


def _run_download(monkeypatch, **kwargs):
    seen = {}

    async def fake_exec(*cmd, **_):
        seen["cmd"] = list(cmd)
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    result = asyncio.run(youtube.download_video("vid", **kwargs))
    template = seen["cmd"][seen["cmd"].index("-o") + 1]
    return result, Path(template).name


def test_default_stem_is_video_id(monkeypatch):
    _, name = _run_download(monkeypatch)
    assert name == "vid.%(ext)s"


def test_per_clip_stem_gives_distinct_files(monkeypatch):
    _, a = _run_download(monkeypatch, file_stem="vid_1")
    _, b = _run_download(monkeypatch, file_stem="vid_2")
    assert a == "vid_1.%(ext)s" and b == "vid_2.%(ext)s" and a != b
