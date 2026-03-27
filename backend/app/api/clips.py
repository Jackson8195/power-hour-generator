"""Clip management endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.schemas import ClipDB, ClipCreate, ClipUpdate, ClipResponse

router = APIRouter(prefix="/api/clips", tags=["clips"])


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
    return db_clip


@router.patch("/{clip_id}", response_model=ClipResponse)
async def update_clip(
    clip_id: int,
    update: ClipUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update clip properties (start/end time, position)."""
    result = await db.execute(select(ClipDB).where(ClipDB.id == clip_id))
    clip = result.scalar_one_or_none()

    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    if update.start_time is not None:
        clip.start_time = update.start_time
    if update.end_time is not None:
        clip.end_time = update.end_time
    if update.position is not None:
        clip.position = update.position

    await db.flush()
    await db.refresh(clip)
    return clip


@router.delete("/{clip_id}")
async def delete_clip(clip_id: int, db: AsyncSession = Depends(get_db)):
    """Remove a clip from a project."""
    result = await db.execute(select(ClipDB).where(ClipDB.id == clip_id))
    clip = result.scalar_one_or_none()

    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    await db.delete(clip)
    return {"status": "deleted", "clip_id": clip_id}


@router.post("/{clip_id}/use-suggestion")
async def use_suggested_segment(clip_id: int, db: AsyncSession = Depends(get_db)):
    """Apply the AI-suggested start/end time for a clip."""
    result = await db.execute(select(ClipDB).where(ClipDB.id == clip_id))
    clip = result.scalar_one_or_none()

    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    if clip.suggested_start is None:
        raise HTTPException(status_code=400, detail="No suggestion available")

    clip.start_time = clip.suggested_start
    clip.end_time = min(clip.suggested_start + 60, clip.duration)

    await db.flush()
    await db.refresh(clip)
    return ClipResponse.model_validate(clip)


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
