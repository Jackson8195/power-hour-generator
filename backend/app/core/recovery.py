"""Startup recovery for jobs that were running when the backend last stopped."""

import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.core.database import async_session
from app.models.schemas import ClipDB, ClipStatus, RenderDB, RenderStatus

logger = logging.getLogger(__name__)

INTERRUPTED_CLIP_MESSAGE = "Download or analysis was interrupted by a restart. Try again."
INTERRUPTED_RENDER_MESSAGE = "Render was interrupted by a restart."


async def recover_interrupted_jobs() -> None:
    """Mark in-flight clips/renders as failed; their background tasks died with the process."""
    async with async_session() as db:
        clips = (
            await db.execute(
                select(ClipDB).where(
                    ClipDB.status.in_([ClipStatus.DOWNLOADING, ClipStatus.ANALYZING])
                )
            )
        ).scalars().all()
        for clip in clips:
            clip.status = ClipStatus.ERROR
            clip.error_message = INTERRUPTED_CLIP_MESSAGE

        renders = (
            await db.execute(
                select(RenderDB).where(
                    RenderDB.status.in_([RenderStatus.QUEUED, RenderStatus.RENDERING])
                )
            )
        ).scalars().all()
        for render in renders:
            render.status = RenderStatus.ERROR
            render.error_message = INTERRUPTED_RENDER_MESSAGE
            render.completed_at = datetime.utcnow()
            if render.output_path:
                Path(render.output_path).unlink(missing_ok=True)

        await db.commit()

    if clips or renders:
        logger.warning(
            "Recovered %d interrupted clip(s) and %d interrupted render(s)",
            len(clips),
            len(renders),
        )
