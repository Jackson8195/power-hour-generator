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
from app.models.schemas import (
    ProjectDB, ClipDB, RenderDB, RenderLibraryEntry, RenderRequest, RenderProgress, RenderStatus, ClipStatus,
)
from app.services.ffmpeg import RenderPipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/render", tags=["render"])

# Active render progress tracking
_render_progress: dict[int, float] = {}


def _build_output_path(project_name: str, project_id: int, render_id: int) -> Path:
    safe_name = project_name.lower().replace(" ", "_")
    filename = f"power_hour_{safe_name}_{project_id}_render_{render_id}.mp4"
    return settings.render_dir / filename


def _build_output_url(output_path: str) -> str:
    return f"/static/renders/{Path(output_path).name}"


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

    # Start render in background
    asyncio.create_task(_run_render(render_id, clip_data, str(output_path), request))

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

        except Exception as e:
            logger.error(f"Render {render_id} failed: {e}")
            render.status = RenderStatus.ERROR
            render.error_message = str(e)
            await db.commit()

        finally:
            _render_progress.pop(render_id, None)


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
        output_path=render.output_path if render.status == RenderStatus.COMPLETE else "",
        error_message=render.error_message,
    )


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
                    "status": "rendering",
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
                            "output_path": render.output_path,
                        })
                        if render.status in (RenderStatus.COMPLETE, RenderStatus.ERROR):
                            break

            await asyncio.sleep(1)

    except WebSocketDisconnect:
        pass
