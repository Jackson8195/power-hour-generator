"""Render pipeline endpoints with WebSocket progress updates."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db, async_session
from app.core.security import public_render_url
from app.models.schemas import (
    ProjectDB, ClipDB, RenderDB, ChangoverClipDB, RenderLibraryEntry, RenderRequest, RenderProgress, RenderStatus, ClipStatus,
)
from app.services.ffmpeg import RenderPipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/render", tags=["render"])

# Active render progress and task tracking
_render_progress: dict[int, float] = {}
_render_tasks: dict[int, asyncio.Task] = {}


def _build_output_path(project_name: str, project_id: int, render_id: int) -> Path:
    safe_name = project_name.lower().replace(" ", "_")
    filename = f"power_hour_{safe_name}_{project_id}_render_{render_id}.mp4"
    return settings.render_dir / filename


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

    # Interleave changeover clip if one exists for this project
    changover_result = await db.execute(
        select(ChangoverClipDB).where(
            ChangoverClipDB.project_id == project_id,
            ChangoverClipDB.status == "ready",
        )
    )
    changover = changover_result.scalar_one_or_none()

    if changover and changover.output_path and Path(changover.output_path).exists():
        interleaved = []
        for i, clip in enumerate(clip_data):
            interleaved.append(clip)
            if i < len(clip_data) - 1:
                interleaved.append({
                    "file_path": changover.output_path,
                    "start_time": 0.0,
                    "end_time": changover.duration,
                    "title": "SHOT!",
                })
        clip_data = interleaved

    # Start render in background
    task = asyncio.create_task(_run_render(render_id, clip_data, str(output_path), request))
    _render_tasks[render_id] = task

    return {"render_id": render_id, "status": "queued"}


async def _run_render(
    render_id: int,
    clips: list[dict],
    output_path: str,
    request: RenderRequest,
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

            pipeline = RenderPipeline(
                clips=clips,
                output_path=output_path,
                resolution=request.resolution,
                transition_type=request.transition_type,
                include_countdown=request.include_countdown,
                progress_callback=progress_callback,
            )

            await pipeline.render()

            render.status = RenderStatus.COMPLETE
            render.progress = 100.0
            render.completed_at = datetime.utcnow()
            await db.commit()

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
    render = result.scalar_one_or_none()
    if not render:
        return None
    return {"render_id": render.id, "status": render.status}


@router.delete("/{render_id}")
async def cancel_render(render_id: int, db: AsyncSession = Depends(get_db)):
    """Cancel a running render or delete a completed one. Removes the file and DB row."""
    task = _render_tasks.pop(render_id, None)
    if task:
        task.cancel()

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
        entries.append(
            RenderLibraryEntry(
                render_id=render.id,
                project_id=project.id,
                project_name=project.name,
                output_url=_build_output_url(render.output_path),
                completed_at=render.completed_at,
            )
        )
    return entries


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
                })
            else:
                # Check if render is complete or errored
                async with async_session() as db:
                    result = await db.execute(
                        select(RenderDB).where(RenderDB.id == render_id)
                    )
                    render = result.scalar_one_or_none()
                    if render:
                        await websocket.send_json({
                            "render_id": render_id,
                            "progress": render.progress,
                            "status": render.status.value,
                            "output_path": _build_output_url(render.output_path) if render.status == RenderStatus.COMPLETE else "",
                            "error_message": render.error_message or "" if render.status == RenderStatus.ERROR else "",
                        })
                        if render.status in (RenderStatus.COMPLETE, RenderStatus.ERROR):
                            break

            await asyncio.sleep(1)

    except WebSocketDisconnect:
        pass
