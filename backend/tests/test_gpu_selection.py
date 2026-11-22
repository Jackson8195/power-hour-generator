"""GPU encoding is automatic: on by default, but only used when a real NVENC test encode works."""

import asyncio

from app.core.config import Settings
from app.services import ffmpeg


def test_nvenc_is_on_by_default_and_can_be_forced_off(monkeypatch):
    monkeypatch.delenv("USE_NVENC", raising=False)
    assert Settings(_env_file=None).use_nvenc is True
    monkeypatch.setenv("USE_NVENC", "0")
    assert Settings(_env_file=None).use_nvenc is False


def test_gpu_used_only_when_flag_on_and_probe_passes(monkeypatch):
    probes = []

    async def probe(result):
        probes.append(result)
        return result

    monkeypatch.setattr(ffmpeg.settings, "use_nvenc", True)
    monkeypatch.setattr(ffmpeg, "_probe_nvenc", lambda: probe(True))
    assert asyncio.run(ffmpeg._should_use_gpu()) is True

    monkeypatch.setattr(ffmpeg, "_probe_nvenc", lambda: probe(False))
    assert asyncio.run(ffmpeg._should_use_gpu()) is False  # no GPU: falls back to CPU

    probes.clear()
    monkeypatch.setattr(ffmpeg.settings, "use_nvenc", False)
    assert asyncio.run(ffmpeg._should_use_gpu()) is False
    assert probes == []  # forced off: never even probes


def test_failed_gpu_encode_retries_on_cpu(monkeypatch):
    seen = []

    class Proc:
        def __init__(self, code):
            self.returncode = code

        async def communicate(self):
            return b"", b"boom"

    async def fake_exec(*cmd, **_):
        seen.append("h264_nvenc" if "h264_nvenc" in cmd else "libx264")
        return Proc(1 if "h264_nvenc" in cmd else 0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    asyncio.run(ffmpeg._run_encode_with_fallback(
        lambda enc: ["ffmpeg", *enc], use_gpu=True, x264_preset="fast", crf=23, label="t"))
    assert seen == ["h264_nvenc", "libx264"]
