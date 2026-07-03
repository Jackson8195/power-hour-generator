"""Shared changeover-clip helpers used by both the manual and AI render paths."""

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.schemas import ChangoverClipDB
from app.services.ffmpeg import build_default_shot_card

logger = logging.getLogger(__name__)


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


async def ensure_default_changeover(
    db: AsyncSession, project_id: int, duration: float = 4.0, resolution: str = "1280x720"
) -> None:
    """Guarantee the project has a transition clip by building the default 3·2·1 →
    "SHOT!" card when none is configured.

    Non-destructive: if a changeover row already exists (e.g. a custom one the user
    built), it is left untouched — the interleave uses it only when it is "ready".
    """
    result = await db.execute(
        select(ChangoverClipDB).where(ChangoverClipDB.project_id == project_id)
    )
    if result.scalar_one_or_none() is not None:
        return

    output_path = str(settings.changeover_dir / f"project_{project_id}_changeover.mp4")
    try:
        await build_default_shot_card(output_path, duration=duration, resolution=resolution)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to build default changeover for project %s: %s", project_id, exc)
        return

    db.add(
        ChangoverClipDB(
            project_id=project_id,
            source_type="default_shot",
            youtube_id="",
            image_path="",
            audio_path="",
            raw_video_path="",
            output_path=output_path,
            duration=duration,
            trim_start=0.0,
            trim_end=0.0,
            status="ready",
            error_message="",
        )
    )
    await db.commit()
