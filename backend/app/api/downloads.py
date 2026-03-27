"""Video download management endpoints."""

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.schemas import ClipDB, ClipStatus
from app.services.youtube import download_video
from app.services.audio_analysis import analyze_audio

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/downloads", tags=["downloads"])

# Track active downloads
_active_downloads: dict[str, asyncio.Task] = {}


@router.post("/{clip_id}/start")
async def start_download(clip_id: int, db: AsyncSession = Depends(get_db)):
    """Start downloading a video for a clip."""
    result = await db.execute(select(ClipDB).where(ClipDB.id == clip_id))
    clip = result.scalar_one_or_none()

    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    if clip.youtube_id in _active_downloads:
        return {"status": "already_downloading", "clip_id": clip_id}

    # Update status
    clip.status = ClipStatus.DOWNLOADING
    await db.commit()

    # Start download in background
    task = asyncio.create_task(_download_and_analyze(clip_id, clip.youtube_id))
    _active_downloads[clip.youtube_id] = task

    return {"status": "started", "clip_id": clip_id}


async def _download_and_analyze(clip_id: int, youtube_id: str):
    """Background task: download video then analyze audio."""
    from app.core.database import async_session

    async with async_session() as db:
        result = await db.execute(select(ClipDB).where(ClipDB.id == clip_id))
        clip = result.scalar_one_or_none()
        if not clip:
            return

        try:
            # Download
            clip.status = ClipStatus.DOWNLOADING
            await db.commit()

            dl_result = await download_video(youtube_id)
            clip.file_path = dl_result["file_path"]
            clip.duration = dl_result["duration"]

            if dl_result.get("title"):
                clip.source_title = dl_result["title"]
            if dl_result.get("artist"):
                clip.source_artist = dl_result["artist"]

            # Analyze audio
            clip.status = ClipStatus.ANALYZING
            await db.commit()

            analysis = await analyze_audio(clip.file_path)
            clip.suggested_start = analysis.get("suggested_start", 0)
            clip.bpm = analysis.get("bpm")
            clip.energy = analysis.get("energy")
            clip.duration = analysis.get("duration", clip.duration)

            # Set default clip selection to suggested segment
            if clip.suggested_start is not None:
                clip.start_time = clip.suggested_start
                clip.end_time = min(
                    clip.suggested_start + 60,
                    clip.duration
                )

            clip.status = ClipStatus.READY
            await db.commit()

        except Exception as e:
            logger.error(f"Download/analysis failed for clip {clip_id}: {e}")
            clip.status = ClipStatus.ERROR
            clip.error_message = str(e)
            await db.commit()

        finally:
            _active_downloads.pop(youtube_id, None)


@router.get("/{clip_id}/status")
async def download_status(clip_id: int, db: AsyncSession = Depends(get_db)):
    """Check download status for a clip."""
    result = await db.execute(select(ClipDB).where(ClipDB.id == clip_id))
    clip = result.scalar_one_or_none()

    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    return {
        "clip_id": clip.id,
        "status": clip.status,
        "file_path": clip.file_path,
        "error_message": clip.error_message,
    }
