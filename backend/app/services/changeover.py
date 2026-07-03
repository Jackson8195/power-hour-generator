"""Shared changeover-clip helpers used by both the manual and AI render paths."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schemas import ChangoverClipDB


async def apply_changeover_interleave(
    db: AsyncSession, project_id: int, clip_data: list[dict]
) -> list[dict]:
    """Insert the project's changeover clip between each pair of song clips.

    Returns ``clip_data`` unchanged when the project has no usable ("ready" with a
    built output file) changeover clip, or when there are fewer than two clips to
    sit a changeover between. Interleaved changeover entries are flagged with
    ``is_changeover`` so the render pipeline skips the countdown/DRINK overlay.
    """
    if len(clip_data) < 2:
        return clip_data

    result = await db.execute(
        select(ChangoverClipDB).where(
            ChangoverClipDB.project_id == project_id,
            ChangoverClipDB.status == "ready",
        )
    )
    changover = result.scalar_one_or_none()

    if not (changover and changover.output_path and Path(changover.output_path).exists()):
        return clip_data

    interleaved: list[dict] = []
    for i, clip in enumerate(clip_data):
        interleaved.append(clip)
        if i < len(clip_data) - 1:
            interleaved.append(
                {
                    "file_path": changover.output_path,
                    "start_time": 0.0,
                    "end_time": changover.duration,
                    "title": "SHOT!",
                    "is_changeover": True,
                }
            )
    return interleaved
