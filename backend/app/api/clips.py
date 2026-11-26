"""Clip management endpoints."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import resolve_managed_path
from app.models.schemas import (
    ClipAnalysisResponse,
    ClipCommitRequest,
    ClipCreate,
    ClipDB,
    ClipResponse,
    ClipUpdate,
)
from app.api.clip_utils import (
    load_clip_analysis,
    media_url_for_path,
    remove_clip_analysis,
    serialize_clip,
)
from app.services.ffmpeg import extract_clip_segment
from app.services.clip_media import clip_output_path, is_trimmed, release_source, trim_clip

router = APIRouter(prefix="/api/clips", tags=["clips"])


# Clips being trimmed right now. One backend process serves every device, so this in-memory set
# is enough to stop two devices trimming the same clip at the same moment.
_trims_in_progress: set[int] = set()


def _clip_output_path(clip_id: int, youtube_id: str) -> Path:
    return clip_output_path(clip_id, youtube_id)


def _clamp_range(clip: ClipDB, start: float, end: float) -> tuple[float, float]:
    """Keep a selection inside the current media file and make sure it is non-empty."""
    duration = float(clip.duration or 0.0)
    if duration > 0:
        if start >= duration:
            raise HTTPException(status_code=400, detail="start_time is beyond the end of the video")
        end = min(end, duration)
    if end <= start:
        raise HTTPException(status_code=400, detail="end_time must be greater than start_time")
    return start, end


@router.post("/", response_model=ClipResponse)
async def create_clip(
    project_id: int,
    clip: ClipCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add a clip to a project."""
    db_clip = ClipDB(
        project_id=project_id,
        position=clip.position,
        source_url=clip.source_url,
        source_title=clip.source_title,
        source_artist=clip.source_artist,
        source_thumbnail=clip.source_thumbnail,
        youtube_id=clip.youtube_id,
    )
    db.add(db_clip)
    await db.flush()
    await db.refresh(db_clip)
    return serialize_clip(db_clip)


@router.patch("/{clip_id}", response_model=ClipResponse)
async def update_clip(
    clip_id: int,
    update: ClipUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update clip draft properties (review range, position)."""
    result = await db.execute(select(ClipDB).where(ClipDB.id == clip_id))
    clip = result.scalar_one_or_none()

    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    if update.position is not None:
        clip.position = update.position

    if update.start_time is not None or update.end_time is not None:
        start = max(0.0, update.start_time if update.start_time is not None else clip.start_time)
        end = max(0.0, update.end_time if update.end_time is not None else clip.end_time)
        start, end = _clamp_range(clip, start, end)
        clip.start_time = start
        clip.end_time = end

    await db.flush()
    await db.refresh(clip)
    return serialize_clip(clip)


@router.get("/{clip_id}/analysis", response_model=ClipAnalysisResponse)
async def get_clip_analysis(clip_id: int, db: AsyncSession = Depends(get_db)):
    """Return waveform bars and recommended regions for clip review."""
    result = await db.execute(select(ClipDB).where(ClipDB.id == clip_id))
    clip = result.scalar_one_or_none()

    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    analysis = load_clip_analysis(clip.id)
    return ClipAnalysisResponse(
        clip_id=clip.id,
        preview_url=media_url_for_path(clip.file_path),
        duration=float(analysis.get("duration", clip.duration or 0.0) or 0.0),
        suggested_start=float(analysis.get("suggested_start", clip.suggested_start or 0.0) or 0.0),
        suggested_end=float(analysis.get("suggested_end", clip.end_time or 0.0) or 0.0),
        waveform=analysis.get("waveform", []),
        highlights=analysis.get("highlights", []),
    )


@router.post("/{clip_id}/use-suggestion", response_model=ClipResponse)
async def use_suggested_segment(clip_id: int, db: AsyncSession = Depends(get_db)):
    """Apply the recommended region as the user's editable draft selection."""
    result = await db.execute(select(ClipDB).where(ClipDB.id == clip_id))
    clip = result.scalar_one_or_none()

    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    analysis = load_clip_analysis(clip.id)
    suggested_start = float(analysis.get("suggested_start", clip.suggested_start or 0.0) or 0.0)
    suggested_end = float(analysis.get("suggested_end", 0.0) or 0.0)

    if suggested_end <= suggested_start:
        raise HTTPException(status_code=400, detail="No suggestion available")

    clip.start_time = suggested_start
    clip.end_time = suggested_end

    await db.flush()
    await db.refresh(clip)
    return serialize_clip(clip)


@router.post("/{clip_id}/commit", response_model=ClipResponse)
async def commit_selection(
    clip_id: int,
    selection: ClipCommitRequest,
    db: AsyncSession = Depends(get_db),
):
    """Trim the chosen segment into a permanent clip file and delete the full source."""
    result = await db.execute(select(ClipDB).where(ClipDB.id == clip_id))
    clip = result.scalar_one_or_none()

    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    if not clip.file_path:
        raise HTTPException(status_code=400, detail="No source media available for this clip")

    resolved_source = resolve_managed_path(clip.file_path, settings.media_dir)
    if not resolved_source or not resolved_source.exists():
        raise HTTPException(status_code=400, detail="No source media available for this clip")

    # Trim guard: another device (or a stale tab) may already have trimmed this clip. Its
    # timestamps refer to the full source, and re-trimming would run ffmpeg over its own input.
    if is_trimmed(clip.file_path) or clip.id in _trims_in_progress:
        raise HTTPException(
            status_code=409,
            detail="This clip was already trimmed (maybe on another device). Refresh to see the trimmed clip.",
        )

    start_time, end_time = _clamp_range(clip, selection.start_time, selection.end_time)

    _trims_in_progress.add(clip.id)
    try:
        # The source is released only after ffmpeg succeeds, and kept while other parts of
        # the same compilation still use it.
        await trim_clip(db, clip, start_time, end_time, extract=extract_clip_segment)
    finally:
        _trims_in_progress.discard(clip.id)

    await db.refresh(clip)
    return serialize_clip(clip)


@router.delete("/{clip_id}")
async def delete_clip(clip_id: int, db: AsyncSession = Depends(get_db)):
    """Remove a clip from a project."""
    result = await db.execute(select(ClipDB).where(ClipDB.id == clip_id))
    clip = result.scalar_one_or_none()

    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    # Compilation parts share one source: keep it while another part still uses it.
    await release_source(db, clip.file_path, clip.id)
    remove_clip_analysis(clip.id)
    await db.delete(clip)
    return {"status": "deleted", "clip_id": clip_id}


@router.post("/reorder")
async def reorder_clips(
    project_id: int,
    clip_ids: list[int],
    db: AsyncSession = Depends(get_db),
):
    """Reorder clips by providing the new order of clip IDs."""
    for position, clip_id in enumerate(clip_ids):
        result = await db.execute(
            select(ClipDB).where(ClipDB.id == clip_id, ClipDB.project_id == project_id)
        )
        clip = result.scalar_one_or_none()
        if clip:
            clip.position = position

    return {"status": "reordered", "count": len(clip_ids)}
