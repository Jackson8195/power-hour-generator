"""Render pipeline endpoints with WebSocket progress updates."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db, async_session
from app.core.security import public_render_url, resolve_managed_path
from app.core.storage import build_render_output_path
from app.models.schemas import (
    ProjectDB, ClipDB, RenderDB, RenderLibraryEntry, RenderRequest, RenderProgress, RenderStatus, ClipStatus,
)
from app.services.ffmpeg import RenderPipeline, extract_clip_segment
from app.services.clip_media import finalize_project_media
from app.services.changeover import apply_changeover_interleave

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/render", tags=["render"])

# Active render progress and task tracking
_render_progress: dict[int, float] = {}
_render_tasks: dict[int, asyncio.Task] = {}
# Whether each active render is using GPU (NVENC) encoding, set once the pipeline probes.
_render_gpu: dict[int, bool] = {}


def _build_output_path(project_name: str, project_id: int, render_id: int) -> Path:
    return build_render_output_path(project_name, project_id, render_id)


def _build_output_url(output_path: str) -> str:
    return public_render_url(output_path)


@router.post("/{project_id}")
async def start_render(
    project_id: int,
    request: RenderRequest,
    db: AsyncSession = Depends(get_db),
):
    """Start rendering a Power Hour video."""
    result = await db.execute(
        select(ProjectDB)
        .options(selectinload(ProjectDB.clips))
        .where(ProjectDB.id == project_id)
    )
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    ready_clips = [
        c for c in project.clips
        if c.status == ClipStatus.READY and c.file_path and c.end_time > c.start_time
    ]
    ready_ids = {c.id for c in ready_clips}
    skipped_clips = [
        c.source_title or f"Clip {c.id}"
        for c in sorted(project.clips, key=lambda c: c.position)
        if c.id not in ready_ids
    ]
    if not ready_clips:
        raise HTTPException(status_code=400, detail="No reviewed clips with a selected range to render")

    from pathlib import Path
    missing = [c.source_title or f"Clip {c.id}" for c in ready_clips if not Path(c.file_path).exists()]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing media files for: {', '.join(missing)}. Delete and re-add these clips.",
        )

    ready_clips.sort(key=lambda c: c.position)

    # Create render record
    render = RenderDB(
        project_id=project_id,
        output_path="",
        resolution=request.resolution,
        status=RenderStatus.QUEUED,
    )
    db.add(render)
    await db.flush()
    await db.refresh(render)

    render_id = render.id
    output_path = _build_output_path(project.name, project_id, render_id)
    render.output_path = str(output_path)
    await db.commit()

    # Prepare clip data for the pipeline
    clip_data = [
        {
            "file_path": clip.file_path,
            "start_time": clip.start_time,
            "end_time": clip.end_time,
            "title": clip.source_title,
        }
        for clip in ready_clips
    ]

    # Interleave the project's changeover clip between songs, if one is ready
    clip_data = await apply_changeover_interleave(db, project_id, clip_data)

    # Start render in background
    task = asyncio.create_task(_run_render(render_id, clip_data, str(output_path), request, project_id))
    _render_tasks[render_id] = task

    return {
        "render_id": render_id,
        "status": "queued",
        "clips_included": len(ready_clips),
        "clips_skipped": skipped_clips,
    }


async def _run_render(
    render_id: int,
    clips: list[dict],
    output_path: str,
    request: RenderRequest,
    project_id: int | None = None,
):
    """Background render task."""
    async with async_session() as db:
        result = await db.execute(select(RenderDB).where(RenderDB.id == render_id))
        render = result.scalar_one_or_none()
        if not render:
            return

        try:
            render.status = RenderStatus.RENDERING
            render.started_at = datetime.utcnow()
            await db.commit()

            def progress_callback(pct: float):
                _render_progress[render_id] = pct

            def on_encoder_selected(gpu_active: bool):
                _render_gpu[render_id] = gpu_active

            pipeline = RenderPipeline(
                clips=clips,
                output_path=output_path,
                resolution=request.resolution,
                transition_type=request.transition_type,
                include_countdown=request.include_countdown,
                progress_callback=progress_callback,
                on_encoder_selected=on_encoder_selected,
            )

            await pipeline.render()

            render.status = RenderStatus.COMPLETE
            render.progress = 100.0
            render.completed_at = datetime.utcnow()
            await db.commit()

            if request.finalize_sources and project_id is not None:
                # Only after a good render: a failed one leaves every source for a retry.
                try:
                    counts = await finalize_project_media(db, project_id, extract=extract_clip_segment)
                    logger.info("Render %s: trimmed %s clips from their sources (%s failed)",
                                render_id, counts["trimmed"], counts["failed"])
                except Exception as exc:
                    logger.error("Render %s: trimming sources after the render failed: %s", render_id, exc)

        except asyncio.CancelledError:
            logger.info(f"Render {render_id} cancelled.")
            Path(output_path).unlink(missing_ok=True)

        except Exception as e:
            logger.error(f"Render {render_id} failed: {e}")
            render.status = RenderStatus.ERROR
            render.error_message = "Render failed."
            await db.commit()

        finally:
            _render_progress.pop(render_id, None)
            _render_tasks.pop(render_id, None)
            _render_gpu.pop(render_id, None)


@router.get("/{render_id}/status", response_model=RenderProgress)
async def render_status(render_id: int, db: AsyncSession = Depends(get_db)):
    """Check render progress."""
    result = await db.execute(select(RenderDB).where(RenderDB.id == render_id))
    render = result.scalar_one_or_none()

    if not render:
        raise HTTPException(status_code=404, detail="Render not found")

    return RenderProgress(
        render_id=render.id,
        status=render.status,
        progress=_render_progress.get(render_id, render.progress),
        output_path=_build_output_url(render.output_path) if render.status == RenderStatus.COMPLETE else "",
        error_message=render.error_message if render.status == RenderStatus.ERROR else "",
        gpu_active=_render_gpu.get(render_id, False),
    )


@router.get("/active/{project_id}")
async def get_active_render(project_id: int, db: AsyncSession = Depends(get_db)):
    """Return the in-progress render for a project, if any."""
    result = await db.execute(
        select(RenderDB)
        .where(RenderDB.project_id == project_id)
        .where(RenderDB.status.in_([RenderStatus.QUEUED, RenderStatus.RENDERING]))
        .order_by(RenderDB.id.desc())
    )
    render = result.scalars().first()
    if not render:
        return None
    return {"render_id": render.id, "status": render.status}


@router.delete("/{render_id}")
async def cancel_render(render_id: int, db: AsyncSession = Depends(get_db)):
    """Cancel a running render or delete a completed one. Removes the file and DB row."""
    task = _render_tasks.pop(render_id, None)
    if task:
        task.cancel()
        # Let the render task unwind (it swallows CancelledError) before its DB row is
        # deleted, so it can't commit against a row that no longer exists.
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=10)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass

    result = await db.execute(select(RenderDB).where(RenderDB.id == render_id))
    render = result.scalar_one_or_none()
    if not render:
        raise HTTPException(status_code=404, detail="Render not found")

    if render.output_path:
        Path(render.output_path).unlink(missing_ok=True)

    await db.delete(render)
    await db.commit()

    return {"status": "deleted"}


@router.get("/library", response_model=list[RenderLibraryEntry])
async def render_library(db: AsyncSession = Depends(get_db)):
    """List completed rendered outputs for mixtape playback."""
    result = await db.execute(
        select(RenderDB, ProjectDB)
        .join(ProjectDB, ProjectDB.id == RenderDB.project_id)
        .where(RenderDB.status == RenderStatus.COMPLETE)
        .order_by(RenderDB.completed_at.desc(), RenderDB.id.desc())
    )

    entries: list[RenderLibraryEntry] = []
    for render, project in result.all():
        if not render.output_path:
            continue
        resolved = resolve_managed_path(render.output_path, settings.render_dir)
        entries.append(
            RenderLibraryEntry(
                render_id=render.id,
                project_id=project.id,
                project_name=project.name,
                output_url=_build_output_url(render.output_path),
                download_url=f"/api/render/{render.id}/download",
                size_bytes=resolved.stat().st_size if resolved and resolved.is_file() else 0,
                completed_at=render.completed_at,
            )
        )
    return entries


@router.get("/{render_id}/download")
async def download_render(render_id: int, db: AsyncSession = Depends(get_db)):
    """The finished MP4 as a file download (Content-Disposition: attachment), so a phone or
    another computer on the Wi-Fi saves it instead of just playing it."""
    render = await db.get(RenderDB, render_id)
    if not render or render.status != RenderStatus.COMPLETE or not render.output_path:
        raise HTTPException(status_code=404, detail="Tape not found")
    resolved = resolve_managed_path(render.output_path, settings.render_dir)
    if not resolved or not resolved.is_file():
        raise HTTPException(status_code=404, detail="The video file for this tape is missing")
    return FileResponse(resolved, media_type="video/mp4", filename=resolved.name)


@router.websocket("/ws/{render_id}")
async def render_progress_ws(websocket: WebSocket, render_id: int):
    """WebSocket endpoint for real-time render progress."""
    await websocket.accept()

    try:
        while True:
            progress = _render_progress.get(render_id)

            if progress is not None:
                await websocket.send_json({
                    "render_id": render_id,
                    "progress": progress,
                    "status": RenderStatus.RENDERING.value,
                    "output_path": "",
                    "error_message": "",
                    "gpu_active": _render_gpu.get(render_id, False),
                })
            else:
                # Check if render is complete or errored
                async with async_session() as db:
                    result = await db.execute(
                        select(RenderDB).where(RenderDB.id == render_id)
                    )
                    render = result.scalar_one_or_none()
                    if not render:
                        break
                    else:
                        await websocket.send_json({
                            "render_id": render_id,
                            "progress": render.progress,
                            "status": render.status.value,
                            "output_path": _build_output_url(render.output_path) if render.status == RenderStatus.COMPLETE else "",
                            "error_message": render.error_message or "" if render.status == RenderStatus.ERROR else "",
                            "gpu_active": _render_gpu.get(render_id, False),
                        })
                        if render.status in (RenderStatus.COMPLETE, RenderStatus.ERROR):
                            break

            await asyncio.sleep(1)

    except WebSocketDisconnect:
        pass
