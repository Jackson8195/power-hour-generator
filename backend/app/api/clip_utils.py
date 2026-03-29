"""Helpers for clip API responses and sidecar analysis files."""

import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.security import resolve_managed_path
from app.models.schemas import ClipDB, ClipResponse


def analysis_file_path(clip_id: int) -> Path:
    return settings.analysis_dir / f"clip_{clip_id}.json"


def save_clip_analysis(clip_id: int, analysis: dict[str, Any]) -> None:
    path = analysis_file_path(clip_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(analysis), encoding="utf-8")


def load_clip_analysis(clip_id: int) -> dict[str, Any]:
    path = analysis_file_path(clip_id)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def remove_clip_analysis(clip_id: int) -> None:
    analysis_file_path(clip_id).unlink(missing_ok=True)


def media_url_for_path(file_path: str) -> str:
    if not file_path:
        return ""
    path = resolve_managed_path(file_path, settings.media_dir)
    if not path:
        return ""
    relative = path.relative_to(settings.media_dir.resolve())
    return f"/media/{relative.as_posix()}"


def serialize_clip(clip: ClipDB) -> ClipResponse:
    from pathlib import Path
    data = ClipResponse.model_validate(clip).model_dump()
    data["file_path"] = ""
    data["preview_url"] = media_url_for_path(clip.file_path)
    data["has_selection"] = bool(clip.file_path and clip.end_time > clip.start_time)
    data["file_missing"] = bool(clip.file_path and not Path(clip.file_path).exists())
    return ClipResponse(**data)
