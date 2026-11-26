"""Clip media that may be shared: the AI flow's compilation parts all point at one source file.

Trimming or deleting one part must never delete a source another clip still reviews or renders
from, so every source removal goes through ``release_source``.
"""

from pathlib import Path
from typing import Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.clip_utils import remove_clip_analysis
from app.core.config import settings
from app.core.security import resolve_managed_path, unlink_managed_file
from app.models.schemas import ClipDB

Extractor = Callable[..., Awaitable[object]]


def clip_output_path(clip_id: int, youtube_id: str) -> Path:
    safe_stem = youtube_id or f"clip_{clip_id}"
    return settings.clips_dir / f"{safe_stem}_{clip_id}.mp4"


def is_trimmed(file_path: str) -> bool:
    """A clip is trimmed once its file lives in the clips folder (sources live in downloads)."""
    resolved = resolve_managed_path(file_path, settings.media_dir) if file_path else None
    return bool(resolved and resolved.parent == settings.clips_dir.resolve())


async def used_by_other_clips(db: AsyncSession, file_path: str, clip_id: int) -> bool:
    if not file_path:
        return False
    count = await db.scalar(
        select(func.count()).select_from(ClipDB).where(ClipDB.file_path == file_path, ClipDB.id != clip_id)
    )
    return bool(count)


async def release_source(db: AsyncSession, file_path: str, clip_id: int) -> bool:
    """Delete ``file_path`` unless another clip still uses it. Returns True when deleted."""
    if not file_path or await used_by_other_clips(db, file_path, clip_id):
        return False
    unlink_managed_file(file_path, settings.media_dir)
    return True


async def trim_clip(db: AsyncSession, clip: ClipDB, start: float, end: float, extract: Extractor) -> None:
    """Cut ``start``..``end`` of the clip's source into its own clip file, then release the
    source (kept while other compilation parts still need it). The source is only touched
    after ``extract`` succeeds. Caller commits."""
    source = clip.file_path
    resolved = resolve_managed_path(source, settings.media_dir)
    if not resolved or not resolved.exists():
        raise FileNotFoundError("No source media available for this clip")
    output_path = clip_output_path(clip.id, clip.youtube_id)
    await extract(source_path=str(resolved), output_path=str(output_path), start_time=start, end_time=end)

    clip.file_path = str(output_path)
    clip.duration = end - start
    clip.start_time = 0.0
    clip.end_time = clip.duration
    clip.suggested_start = None
    await db.flush()  # this clip no longer counts as a user of the source
    if resolved != output_path.resolve():
        await release_source(db, source, clip.id)
    remove_clip_analysis(clip.id)


async def finalize_project_media(db: AsyncSession, project_id: int, extract: Extractor) -> dict:
    """After a successful render: trim every clip still on its full source to its saved range,
    release those sources, and drop the AI transitions' kept source videos.

    Each clip is independent: one that fails keeps its source (and can still be re-rendered).
    Returns counts for the log."""
    from app.models.schemas import ChangoverClipDB, ClipStatus  # local: keep import graph small

    clips = (
        await db.execute(
            select(ClipDB).where(ClipDB.project_id == project_id, ClipDB.status == ClipStatus.READY)
        )
    ).scalars().all()
    trimmed = failed = 0
    for clip in clips:
        if not clip.file_path or is_trimmed(clip.file_path) or clip.end_time <= clip.start_time:
            continue
        try:
            await trim_clip(db, clip, clip.start_time, clip.end_time, extract)
            await db.commit()
            trimmed += 1
        except Exception:
            # trim_clip changes nothing until ffmpeg has succeeded, so the clip simply keeps
            # its source and range and can still be rendered again.
            failed += 1

    rows = (
        await db.execute(
            select(ChangoverClipDB).where(ChangoverClipDB.project_id == project_id, ChangoverClipDB.origin == "ai")
        )
    ).scalars().all()
    for row in rows:
        path = row.raw_video_path or ""
        if path:
            try:
                file = Path(path).resolve()
                if file.parent == settings.changeover_dir.resolve():
                    file.unlink(missing_ok=True)
                row.raw_video_path = ""
            except OSError:
                # Still open somewhere (Windows locks open files): keep the reference so it isn't
                # orphaned; project deletion removes every project_<id>_ai_* file anyway.
                pass
    await db.commit()
    return {"trimmed": trimmed, "failed": failed}
