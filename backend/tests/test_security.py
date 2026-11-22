from pathlib import Path

from app.core.config import settings
from app.core.security import (
    is_allowed_cast_video_url,
    resolve_managed_path,
    unlink_managed_file,
)


def test_resolve_accepts_path_inside_root():
    inside = settings.media_dir / "clips" / "a.mp4"
    assert resolve_managed_path(str(inside), settings.media_dir) == inside.resolve()


def test_resolve_rejects_outside_and_traversal():
    assert resolve_managed_path("/etc/passwd", settings.media_dir) is None
    sneaky = settings.media_dir / ".." / ".." / "etc" / "passwd"
    assert resolve_managed_path(str(sneaky), settings.media_dir) is None
    assert resolve_managed_path("", settings.media_dir) is None


def test_unlink_only_touches_managed_files(tmp_path):
    outside = tmp_path / "keep.txt"
    outside.write_text("x")
    assert unlink_managed_file(str(outside), settings.media_dir) is False
    assert outside.exists()

    inside = settings.media_dir / "downloads" / "del.mp4"
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_text("x")
    assert unlink_managed_file(str(inside), settings.media_dir) is True
    assert not inside.exists()


def test_cast_url_must_be_an_existing_render():
    rendered = settings.render_dir / "ok.mp4"
    rendered.parent.mkdir(parents=True, exist_ok=True)
    rendered.write_bytes(b"x")
    assert is_allowed_cast_video_url("http://host:8000/static/ok.mp4")
    assert not is_allowed_cast_video_url("http://host:8000/static/missing.mp4")
    assert not is_allowed_cast_video_url("http://evil.example/other/ok.mp4")
    assert not is_allowed_cast_video_url("")
