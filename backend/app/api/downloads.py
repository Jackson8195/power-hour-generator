"""Video download management endpoints."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.core.security import resolve_managed_path, unlink_managed_file
from app.models.schemas import ClipDB, ClipStatus
from app.api.clip_utils import remove_clip_analysis, save_clip_analysis
from app.services.youtube import download_video
from app.services.audio_analysis import analyze_audio

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/downloads", tags=["downloads"])

# Track active downloads
_active_downloads: dict[str, asyncio.Task] = {}


DOWNLOAD_FAILURE_MESSAGE = "Download or analysis failed for this clip."


@router.post("/{clip_id}/start")
async def start_download(clip_id: int, db: AsyncSession = Depends(get_db)):
    """Start downloading a video for a clip."""
    result = await db.execute(select(ClipDB).where(ClipDB.id == clip_id))
    clip = result.scalar_one_or_none()

    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    if clip.youtube_id in _active_downloads:
        return {"status": "already_downloading", "clip_id": clip_id}

    if clip.file_path:
        unlink_managed_file(clip.file_path, settings.media_dir)
        clip.file_path = ""
    remove_clip_analysis(clip.id)

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
            source_file_path = dl_result["file_path"]
            resolved_source = resolve_managed_path(source_file_path, settings.media_dir)
            if not resolved_source or not resolved_source.exists():
                raise RuntimeError("Download completed but no local media file was found")

            if dl_result.get("title"):
                clip.source_title = dl_result["title"]
            if dl_result.get("artist"):
                clip.source_artist = dl_result["artist"]

            # Analyze audio
            clip.status = ClipStatus.ANALYZING
            await db.commit()

            analysis = await analyze_audio(str(resolved_source))
            if not analysis.get("waveform") or float(analysis.get("duration", 0) or 0) <= 0:
                raise RuntimeError("Audio analysis did not produce waveform data")
            clip.bpm = analysis.get("bpm")
            clip.energy = analysis.get("energy")
            clip.file_path = str(resolved_source)
            clip.duration = float(analysis.get("duration", dl_result.get("duration", 0)) or 0)
            clip.start_time = 0.0
            clip.end_time = 0.0
            clip.suggested_start = float(analysis.get("suggested_start", 0) or 0)
            clip.error_message = ""

            save_clip_analysis(clip.id, analysis)

            clip.status = ClipStatus.READY
            await db.commit()

        except Exception as e:
            logger.error(f"Download/analysis failed for clip {clip_id}: {e}")
            clip.status = ClipStatus.ERROR
            clip.error_message = DOWNLOAD_FAILURE_MESSAGE
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
        "has_media": bool(clip.file_path),
        "error_message": clip.error_message if clip.status == ClipStatus.ERROR else "",
    }
