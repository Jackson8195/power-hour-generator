"""Shared changeover-clip helpers used by both the manual and AI render paths."""

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.schemas import ChangoverClipDB, RenderRequest
from app.services.ffmpeg import build_default_shot_card
from app.services.transition_fx import CARD_SECONDS, DEFAULT_SOUND, build_art_card, card_length, pick_bundled_art

logger = logging.getLogger(__name__)


def render_resolution() -> str:
    """The resolution renders use by default. Transitions are built at this size so they
    always match the render (the render pipeline still scales every clip as a safety net)."""
    return RenderRequest.model_fields["resolution"].default


async def apply_changeover_interleave(
    db: AsyncSession, project_id: int, clip_data: list[dict]
) -> list[dict]:
    """Insert the project's changeover clips between each pair of song clips.

    With one usable changeover it repeats between every pair; with several (AI-created) it
    cycles through them in ``position`` order. Returns ``clip_data`` unchanged when the
    project has no usable ("ready" with a built output file) changeover, or when there are
    fewer than two clips to sit one between. Interleaved entries are flagged with
    ``is_changeover`` so the render pipeline skips the countdown/DRINK overlay.
    """
    if len(clip_data) < 2:
        return clip_data

    result = await db.execute(
        select(ChangoverClipDB)
        .where(
            ChangoverClipDB.project_id == project_id,
            ChangoverClipDB.status == "ready",
        )
        .order_by(ChangoverClipDB.position, ChangoverClipDB.id)
    )
    changeovers = [
        row for row in result.scalars().all()
        if row.output_path and Path(row.output_path).exists()
    ]
    if not changeovers:
        return clip_data

    interleaved: list[dict] = []
    for i, clip in enumerate(clip_data):
        interleaved.append(clip)
        if i < len(clip_data) - 1:
            changeover = changeovers[i % len(changeovers)]
            interleaved.append(
                {
                    "file_path": changeover.output_path,
                    "start_time": 0.0,
                    "end_time": changeover.duration,
                    "title": changeover.label or "SHOT!",
                    "is_changeover": True,
                }
            )
    return interleaved


async def ensure_default_changeover(
    db: AsyncSession, project_id: int, duration: float = CARD_SECONDS, resolution: str | None = None
) -> None:
    """Guarantee the project has a transition clip by building the default animated card
    (corner 3·2·1 countdown, then "SHOT!" on the default drink cue) when none is configured.

    Non-destructive: if a changeover row already exists (e.g. a custom one the user
    built), it is left untouched — the interleave uses it only when it is "ready".
    """
    result = await db.execute(
        select(ChangoverClipDB.id).where(ChangoverClipDB.project_id == project_id).limit(1)
    )
    if result.scalar_one_or_none() is not None:
        return

    output_path = str(settings.changeover_dir / f"project_{project_id}_changeover.mp4")
    duration = card_length(duration)
    art = pick_bundled_art(project_id)
    try:
        if art:
            # Bundled drink art (shot glass, beer, ...) with the corner countdown and default cue.
            await build_art_card(
                output_path, str(art), duration=duration,
                resolution=resolution or render_resolution(), hit_text="SHOT!", sound=DEFAULT_SOUND,
            )
        else:
            await build_default_shot_card(
                output_path, duration=duration, resolution=resolution or render_resolution()
            )
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
