"""Changeover (shot notification) clip endpoints."""

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session, get_db
from app.models.schemas import ChangoverClipDB, ChangoverClipResponse
from app.services.ffmpeg import build_changeover_clip
from app.services.youtube import download_video, download_audio_only

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/changeover", tags=["changeover"])

_ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_ALLOWED_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
_ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


# ─── Helpers ─────────────────────────────────────────────

def _preview_url(output_path: str) -> str:
    if not output_path:
        return ""
    filename = Path(output_path).name
    return f"/media/changeover/{filename}"


def _raw_video_url(raw_video_path: str) -> str:
    if not raw_video_path:
        return ""
    filename = Path(raw_video_path).name
    return f"/media/changeover/{filename}"


def _to_response(row: ChangoverClipDB) -> ChangoverClipResponse:
    return ChangoverClipResponse(
        id=row.id,
        project_id=row.project_id,
        source_type=row.source_type or "image_audio",
        youtube_id=row.youtube_id or "",
        image_path=row.image_path or "",
        audio_path=row.audio_path or "",
        raw_video_path=row.raw_video_path or "",
        output_path=row.output_path or "",
        duration=row.duration or 3.0,
        trim_start=row.trim_start or 0.0,
        trim_end=row.trim_end or 0.0,
        status=row.status or "pending",
        error_message=row.error_message or "",
        preview_url=_preview_url(row.output_path or ""),
        raw_video_url=_raw_video_url(row.raw_video_path or ""),
    )


def delete_changeover_media_files(project_id: int) -> None:
    """Delete all changeover media files for a project. Also used by project deletion."""
    changeover_dir = settings.changeover_dir
    for pattern in [
        f"project_{project_id}_image.*",
        f"project_{project_id}_audio.*",
        f"project_{project_id}_raw.*",
        f"project_{project_id}_changeover.mp4",
    ]:
        for f in changeover_dir.glob(pattern):
            f.unlink(missing_ok=True)


# ─── GET /api/changeover/{project_id} ────────────────────

@router.get("/{project_id}", response_model=ChangoverClipResponse)
async def get_changeover_clip(project_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ChangoverClipDB).where(ChangoverClipDB.project_id == project_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="No changeover clip for this project")
    return _to_response(row)


# ─── POST /api/changeover/{project_id} — image + audio mode ──

@router.post("/{project_id}", response_model=ChangoverClipResponse)
async def build_image_audio_changeover(
    project_id: int,
    image: UploadFile | None = None,
    audio: UploadFile | None = None,
    duration: float = Form(3.0),
    db: AsyncSession = Depends(get_db),
):
    if not image and not audio:
        raise HTTPException(status_code=422, detail="At least one of image or audio is required")
    if not (1.0 <= duration <= 10.0):
        raise HTTPException(status_code=422, detail="Duration must be between 1 and 10 seconds")

    if image:
        img_ext = Path(image.filename or "").suffix.lower()
        if img_ext not in _ALLOWED_IMAGE_EXTS:
            raise HTTPException(status_code=422, detail=f"Image type {img_ext!r} not allowed")
    if audio:
        aud_ext = Path(audio.filename or "").suffix.lower()
        if aud_ext not in _ALLOWED_AUDIO_EXTS:
            raise HTTPException(status_code=422, detail=f"Audio type {aud_ext!r} not allowed")

    # Clean up old files
    delete_changeover_media_files(project_id)

    # Save uploads
    image_path = ""
    audio_path = ""
    if image:
        img_ext = Path(image.filename or "").suffix.lower()
        image_path = str(settings.changeover_dir / f"project_{project_id}_image{img_ext}")
        with open(image_path, "wb") as f:
            f.write(await image.read())
    if audio:
        aud_ext = Path(audio.filename or "").suffix.lower()
        audio_path = str(settings.changeover_dir / f"project_{project_id}_audio{aud_ext}")
        with open(audio_path, "wb") as f:
            f.write(await audio.read())

    output_path = str(settings.changeover_dir / f"project_{project_id}_changeover.mp4")

    # Upsert DB row
    result = await db.execute(
        select(ChangoverClipDB).where(ChangoverClipDB.project_id == project_id)
    )
    row = result.scalar_one_or_none()
    if row:
        row.source_type = "image_audio"
        row.youtube_id = ""
        row.image_path = image_path
        row.audio_path = audio_path
        row.raw_video_path = ""
        row.output_path = ""
        row.duration = duration
        row.trim_start = 0.0
        row.trim_end = 0.0
        row.status = "pending"
        row.error_message = ""
    else:
        row = ChangoverClipDB(
            project_id=project_id,
            source_type="image_audio",
            youtube_id="",
            image_path=image_path,
            audio_path=audio_path,
            raw_video_path="",
            output_path="",
            duration=duration,
            trim_start=0.0,
            trim_end=0.0,
            status="pending",
            error_message="",
        )
        db.add(row)
    await db.commit()
    await db.refresh(row)

    # Build the clip (synchronous — short clip)
    try:
        await build_changeover_clip(
            output_path=output_path,
            duration=duration,
            resolution="1280x720",
            image_path=image_path or None,
            audio_path=audio_path or None,
        )
        row.output_path = output_path
        row.status = "ready"
    except Exception as e:
        row.status = "error"
        row.error_message = str(e)[:500]
        logger.error(f"Changeover build failed for project {project_id}: {e}")

    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ─── POST /api/changeover/{project_id}/youtube — start YouTube download ──

@router.post("/{project_id}/youtube", response_model=ChangoverClipResponse)
async def start_youtube_changeover(
    project_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    youtube_id = (body.get("youtube_id") or "").strip()
    if not youtube_id:
        raise HTTPException(status_code=422, detail="youtube_id is required")

    delete_changeover_media_files(project_id)

    result = await db.execute(
        select(ChangoverClipDB).where(ChangoverClipDB.project_id == project_id)
    )
    row = result.scalar_one_or_none()
    if row:
        row.source_type = "youtube"
        row.youtube_id = youtube_id
        row.image_path = ""
        row.audio_path = ""
        row.raw_video_path = ""
        row.output_path = ""
        row.trim_start = 0.0
        row.trim_end = 0.0
        row.status = "downloading"
        row.error_message = ""
    else:
        row = ChangoverClipDB(
            project_id=project_id,
            source_type="youtube",
            youtube_id=youtube_id,
            image_path="",
            audio_path="",
            raw_video_path="",
            output_path="",
            duration=3.0,
            trim_start=0.0,
            trim_end=0.0,
            status="downloading",
            error_message="",
        )
        db.add(row)
    await db.commit()
    await db.refresh(row)

    asyncio.create_task(_download_changeover_video(project_id, youtube_id))
    return _to_response(row)


async def _download_changeover_video(project_id: int, youtube_id: str) -> None:
    async with async_session() as db:
        result = await db.execute(
            select(ChangoverClipDB).where(ChangoverClipDB.project_id == project_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            return
        try:
            info = await download_video(youtube_id, output_dir=settings.changeover_dir)
            downloaded_path = Path(info["file_path"])

            # Rename to stable project-scoped name
            raw_path = settings.changeover_dir / f"project_{project_id}_raw.mp4"
            if downloaded_path.exists() and downloaded_path != raw_path:
                downloaded_path.rename(raw_path)

            row.raw_video_path = str(raw_path)
            row.status = "downloaded"
        except Exception as e:
            row.status = "error"
            row.error_message = str(e)[:500]
            logger.error(f"Changeover YouTube download failed for project {project_id}: {e}")
        await db.commit()


# ─── POST /api/changeover/{project_id}/youtube-audio — audio-only rip ──

@router.post("/{project_id}/youtube-audio", response_model=ChangoverClipResponse)
async def start_youtube_audio_changeover(
    project_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    youtube_id = (body.get("youtube_id") or "").strip()
    if not youtube_id:
        raise HTTPException(status_code=422, detail="youtube_id is required")

    delete_changeover_media_files(project_id)

    result = await db.execute(
        select(ChangoverClipDB).where(ChangoverClipDB.project_id == project_id)
    )
    row = result.scalar_one_or_none()
    if row:
        row.source_type = "youtube_audio"
        row.youtube_id = youtube_id
        row.image_path = ""
        row.audio_path = ""
        row.raw_video_path = ""
        row.output_path = ""
        row.trim_start = 0.0
        row.trim_end = 0.0
        row.status = "downloading"
        row.error_message = ""
    else:
        row = ChangoverClipDB(
            project_id=project_id,
            source_type="youtube_audio",
            youtube_id=youtube_id,
            image_path="",
            audio_path="",
            raw_video_path="",
            output_path="",
            duration=3.0,
            trim_start=0.0,
            trim_end=0.0,
            status="downloading",
            error_message="",
        )
        db.add(row)
    await db.commit()
    await db.refresh(row)

    asyncio.create_task(_download_changeover_audio(project_id, youtube_id))
    return _to_response(row)


async def _download_changeover_audio(project_id: int, youtube_id: str) -> None:
    async with async_session() as db:
        result = await db.execute(
            select(ChangoverClipDB).where(ChangoverClipDB.project_id == project_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            return
        try:
            audio_path = await download_audio_only(youtube_id, output_dir=settings.changeover_dir)
            # Rename to stable project-scoped name
            downloaded = Path(audio_path)
            stable_path = settings.changeover_dir / f"project_{project_id}_raw_audio{downloaded.suffix}"
            if downloaded.exists() and downloaded != stable_path:
                downloaded.rename(stable_path)

            row.raw_video_path = str(stable_path)  # reuse raw_video_path field to store raw audio
            row.status = "downloaded"
        except Exception as e:
            row.status = "error"
            row.error_message = str(e)[:500]
            logger.error(f"Changeover YouTube audio download failed for project {project_id}: {e}")
        await db.commit()


# ─── POST /api/changeover/{project_id}/upload-video — local video upload ──

@router.post("/{project_id}/upload-video", response_model=ChangoverClipResponse)
async def upload_video_changeover(
    project_id: int,
    video: UploadFile,
    db: AsyncSession = Depends(get_db),
):
    vid_ext = Path(video.filename or "").suffix.lower()
    if vid_ext not in _ALLOWED_VIDEO_EXTS:
        raise HTTPException(status_code=422, detail=f"Video type {vid_ext!r} not allowed")

    delete_changeover_media_files(project_id)

    raw_path = str(settings.changeover_dir / f"project_{project_id}_raw{vid_ext}")
    with open(raw_path, "wb") as f:
        f.write(await video.read())

    result = await db.execute(
        select(ChangoverClipDB).where(ChangoverClipDB.project_id == project_id)
    )
    row = result.scalar_one_or_none()
    if row:
        row.source_type = "local_video"
        row.youtube_id = ""
        row.image_path = ""
        row.audio_path = ""
        row.raw_video_path = raw_path
        row.output_path = ""
        row.trim_start = 0.0
        row.trim_end = 0.0
        row.status = "downloaded"
        row.error_message = ""
    else:
        row = ChangoverClipDB(
            project_id=project_id,
            source_type="local_video",
            youtube_id="",
            image_path="",
            audio_path="",
            raw_video_path=raw_path,
            output_path="",
            duration=3.0,
            trim_start=0.0,
            trim_end=0.0,
            status="downloaded",
            error_message="",
        )
        db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ─── POST /api/changeover/{project_id}/build — commit trim + build final clip ──

@router.post("/{project_id}/build", response_model=ChangoverClipResponse)
async def build_video_changeover(
    project_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    trim_start = float(body.get("trim_start", 0.0))
    trim_end = float(body.get("trim_end", 0.0))
    audio_trim_start = float(body.get("audio_trim_start", 0.0))
    duration = float(body.get("duration", 0.0))

    result = await db.execute(
        select(ChangoverClipDB).where(ChangoverClipDB.project_id == project_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="No changeover clip for this project")
    if row.source_type not in ("youtube", "local_video", "youtube_audio"):
        raise HTTPException(status_code=422, detail="Build endpoint is only for video/audio-mode changeover clips")
    if not row.raw_video_path or not Path(row.raw_video_path).exists():
        raise HTTPException(status_code=422, detail="Raw file not found — re-download or re-upload")

    output_path = str(settings.changeover_dir / f"project_{project_id}_changeover.mp4")

    if row.source_type == "youtube_audio":
        # Audio-only rip — build like image+audio but audio comes from the downloaded file
        if trim_end <= trim_start and duration <= 0:
            raise HTTPException(status_code=422, detail="Provide either trim range or duration")
        clip_duration = (trim_end - trim_start) if trim_end > trim_start else duration
        if clip_duration > 10.0:
            raise HTTPException(status_code=422, detail="Clip duration cannot exceed 10 seconds")
        try:
            await build_changeover_clip(
                output_path=output_path,
                duration=clip_duration,
                resolution="1280x720",
                image_path=row.image_path or None,
                audio_path=row.raw_video_path,
                audio_trim_start=audio_trim_start,
            )
            row.output_path = output_path
            row.trim_start = audio_trim_start
            row.trim_end = audio_trim_start + clip_duration
            row.duration = clip_duration
            row.status = "ready"
            row.error_message = ""
        except Exception as e:
            row.status = "error"
            row.error_message = str(e)[:500]
            logger.error(f"Changeover build failed for project {project_id}: {e}")
    else:
        if trim_end <= trim_start:
            raise HTTPException(status_code=422, detail="trim_end must be greater than trim_start")
        if (trim_end - trim_start) > 10.0:
            raise HTTPException(status_code=422, detail="Clip duration cannot exceed 10 seconds")
        clip_duration = trim_end - trim_start
        try:
            await build_changeover_clip(
                output_path=output_path,
                duration=clip_duration,
                resolution="1280x720",
                video_path=row.raw_video_path,
                trim_start=trim_start,
                trim_end=trim_end,
            )
            row.output_path = output_path
            row.trim_start = trim_start
            row.trim_end = trim_end
            row.duration = clip_duration
            row.status = "ready"
            row.error_message = ""
        except Exception as e:
            row.status = "error"
            row.error_message = str(e)[:500]
            logger.error(f"Changeover build failed for project {project_id}: {e}")

    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ─── PATCH /api/changeover/{project_id}/image — set image for youtube_audio mode ──

@router.patch("/{project_id}/image", response_model=ChangoverClipResponse)
async def set_changeover_image(
    project_id: int,
    image: UploadFile | None = None,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ChangoverClipDB).where(ChangoverClipDB.project_id == project_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="No changeover clip for this project")

    if image:
        img_ext = Path(image.filename or "").suffix.lower()
        if img_ext not in _ALLOWED_IMAGE_EXTS:
            raise HTTPException(status_code=422, detail=f"Image type {img_ext!r} not allowed")
        # Remove old image if present
        if row.image_path:
            Path(row.image_path).unlink(missing_ok=True)
        image_path = str(settings.changeover_dir / f"project_{project_id}_image{img_ext}")
        with open(image_path, "wb") as f:
            f.write(await image.read())
        row.image_path = image_path
    else:
        # Clear image
        if row.image_path:
            Path(row.image_path).unlink(missing_ok=True)
        row.image_path = ""

    await db.commit()
    await db.refresh(row)
    return _to_response(row)


# ─── DELETE /api/changeover/{project_id} ─────────────────

@router.delete("/{project_id}")
async def delete_changeover_clip(project_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ChangoverClipDB).where(ChangoverClipDB.project_id == project_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="No changeover clip for this project")

    delete_changeover_media_files(project_id)
    await db.delete(row)
    await db.commit()
    return {"status": "deleted"}
