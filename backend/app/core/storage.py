"""Storage layout migration helpers."""

from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session
from app.core.security import resolve_managed_path
from app.models.schemas import ClipDB, RenderDB


async def migrate_storage_layout() -> None:
    """Move legacy media files into organized subfolders and update DB paths."""
    settings.ensure_dirs()

    async with async_session() as db:
        await _migrate_clip_files(db)
        await _migrate_render_files(db)
        await db.commit()


async def _migrate_clip_files(db) -> None:
    result = await db.execute(select(ClipDB))
    clips = result.scalars().all()

    for clip in clips:
        if not clip.file_path:
            continue

        source = resolve_managed_path(clip.file_path, settings.media_dir)
        if not source:
            continue
        if not source.exists():
            continue

        target = source
        if source.parent == settings.media_dir.resolve() or source.parent == settings.media_dir:
            target = settings.downloads_dir / source.name
        elif source.parent.name == "clips":
            target = settings.clips_dir / source.name

        if target != source:
            target.parent.mkdir(parents=True, exist_ok=True)
            source.replace(target)
            clip.file_path = str(target)

    for source in settings.media_dir.glob("*.mp4"):
        target = settings.downloads_dir / source.name
        if not target.exists():
            source.replace(target)


async def _migrate_render_files(db) -> None:
    result = await db.execute(select(RenderDB))
    renders = result.scalars().all()

    legacy_static_dir = (settings.media_dir.parent / "static" / "renders").resolve()

    for render in renders:
        if not render.output_path:
            continue

        source = Path(render.output_path)
        if not source.is_absolute():
            source = (settings.media_dir.parent / source).resolve()
        else:
            source = source.resolve()

        if not source.exists():
            continue

        allowed_legacy_roots = {
            settings.render_dir.resolve(),
            legacy_static_dir,
        }
        if not any(source == root or root in source.parents for root in allowed_legacy_roots):
            continue

        target = settings.render_dir / source.name
        if target != source:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                source.replace(target)
            elif source.exists() and source != target:
                source.unlink(missing_ok=True)
            render.output_path = str(target)

    if legacy_static_dir.exists():
        for source in legacy_static_dir.glob("*.mp4"):
            target = settings.render_dir / source.name
            if not target.exists():
                source.replace(target)
