"""Review AI transitions before the build: generate a set, then trash/regenerate/add one at a time.

The project is pre-created from the proposal (same as the custom-transition flow), the AI
transitions are built into it here, and approving with ``ai_transitions_reviewed`` reuses
them instead of generating new ones during the build.
"""

import asyncio
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session, get_db
from app.models.schemas import ChangoverClipDB, ProjectDB, RenderDB
from app.services import ai_transitions as ait

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai-transitions", tags=["ai-transitions"])

# Hold references so fire-and-forget tasks aren't garbage-collected mid-run.
_tasks: set[asyncio.Task] = set()
_PROMPT_PREFIX = "AI generated from prompt: "


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# The user's call word ("DRINK!"). None = keep the current one / let the AI pick; "" = no text.
DrinkText = Field(None, max_length=ait.DRINK_TEXT_CHARS * 2)


class GenerateRequest(BaseModel):
    prompt: str = Field("", max_length=1000)  # the user's direction for the transitions
    count: int = Field(4, ge=1, le=ait.MAX_COUNT)
    sources: Literal["cards", "youtube", "both"] = "both"
    drink_text: str | None = DrinkText


class RegenerateRequest(BaseModel):
    prompt: str = Field("", max_length=1000)
    kind: Literal["card", "youtube"] | None = None
    drink_text: str | None = DrinkText


class TrimRequest(BaseModel):
    start: float = Field(..., ge=0)  # seconds into the kept full source
    end: float = Field(..., gt=0)
    drink_text: str | None = DrinkText


class TextRequest(BaseModel):
    drink_text: str = Field("", max_length=ait.DRINK_TEXT_CHARS * 2)


def _source_url(row: ChangoverClipDB) -> str:
    path = row.raw_video_path or ""
    if row.source_type != "ai_youtube" or not path or not Path(path).is_file():
        return ""
    return f"/media/changeover/{Path(path).name}"


def _preview_url(row: ChangoverClipDB) -> str:
    if not row.output_path or row.status != "ready":
        return ""
    return f"/media/changeover/{Path(row.output_path).name}"


def _to_item(row: ChangoverClipDB) -> dict:
    spec = ait._spec_from_row(row)
    return {
        "id": row.id,
        "position": row.position or 0,
        "label": row.label or "",
        "kind": "youtube" if row.source_type == "ai_youtube" else "card",
        "youtube_id": row.youtube_id or "",
        "status": row.status or "",
        "error_message": row.error_message or "",
        "duration": row.duration or 0.0,
        "preview_url": _preview_url(row),
        # Video moments keep their whole source (until the render) so they can be re-trimmed.
        "source_url": _source_url(row),
        "source_seconds": spec.source_seconds,
        "waveform": spec.waveform or [],
        "trim_start": row.trim_start or 0.0,
        "trim_end": row.trim_end or 0.0,
        "drink_text": spec.hit_text,
    }


async def _project_or_404(db: AsyncSession, project_id: int) -> ProjectDB:
    project = await db.get(ProjectDB, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    rendered = await db.execute(select(RenderDB.id).where(RenderDB.project_id == project_id).limit(1))
    if rendered.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Project already has a render")
    return project


def _theme(project: ProjectDB) -> str:
    description = project.description or ""
    if description.startswith(_PROMPT_PREFIX):
        return description[len(_PROMPT_PREFIX):]
    return description or project.name or "power hour"


def _busy(project_id: int) -> bool:
    return ait.review_state(project_id)["state"] != "idle"


@router.get("/{project_id}")
async def list_ai_transitions(project_id: int, db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(ChangoverClipDB)
            .where(ChangoverClipDB.project_id == project_id, ChangoverClipDB.origin == "ai")
            .order_by(ChangoverClipDB.position, ChangoverClipDB.id)
        )
    ).scalars().all()
    state = ait.review_state(project_id)
    return {"state": state["state"], "error": state["error"], "transitions": [_to_item(r) for r in rows]}


@router.post("/{project_id}/generate", status_code=202)
async def generate_ai_transitions(project_id: int, body: GenerateRequest, db: AsyncSession = Depends(get_db)):
    project = await _project_or_404(db, project_id)
    if _busy(project_id):
        raise HTTPException(status_code=409, detail="Transitions are already being generated")
    theme = _theme(project)
    ait._set_review(project_id, "planning")  # visible to the very next poll

    async def run() -> None:
        try:
            async with async_session() as session:
                await ait.create_ai_transitions(
                    session, project_id, theme, body.count, body.sources, transition_prompt=body.prompt,
                    drink_text=body.drink_text,
                )
        except Exception as exc:  # create_ai_transitions records the error for the UI
            logger.error("AI transition generation failed for project %s: %s", project_id, exc)

    _spawn(run())
    return {"state": "planning"}


async def _regenerate(
    project_id: int, row_id: int, theme: str, prompt: str, kind: str | None, drink_text: str | None = None
) -> None:
    try:
        async with async_session() as session:
            await ait.regenerate_ai_transition(session, project_id, row_id, theme, prompt, kind, drink_text=drink_text)
    except Exception as exc:
        logger.error("Regenerating AI transition %s failed: %s", row_id, exc)
        async with async_session() as session:
            row = await session.get(ChangoverClipDB, row_id)
            if row is not None and row.status == "building":
                row.status = "error"
                row.error_message = str(exc)[:500]
                await session.commit()


@router.post("/{project_id}/{row_id}/regenerate", status_code=202)
async def regenerate_ai_transition(
    project_id: int, row_id: int, body: RegenerateRequest, db: AsyncSession = Depends(get_db)
):
    project = await _project_or_404(db, project_id)
    row = await db.get(ChangoverClipDB, row_id)
    if row is None or row.project_id != project_id or row.origin != "ai":
        raise HTTPException(status_code=404, detail="Transition not found")
    if row.status == "building" or _busy(project_id):
        raise HTTPException(status_code=409, detail="That transition is still being built")
    row.status = "building"
    row.error_message = ""
    await db.commit()
    _spawn(_regenerate(project_id, row_id, _theme(project), body.prompt, body.kind, body.drink_text))
    return _to_item(row)


async def _trim(project_id: int, row_id: int, start: float, end: float, drink_text: str | None = None) -> None:
    try:
        async with async_session() as session:
            await ait.trim_ai_transition(session, project_id, row_id, start, end, drink_text=drink_text)
    except Exception as exc:
        logger.error("Trimming AI transition %s failed: %s", row_id, exc)
        async with async_session() as session:
            row = await session.get(ChangoverClipDB, row_id)
            if row is not None and row.status == "building":
                row.status = "error"
                row.error_message = str(exc)[:500]
                await session.commit()


@router.post("/{project_id}/{row_id}/trim", status_code=202)
async def trim_ai_transition(project_id: int, row_id: int, body: TrimRequest, db: AsyncSession = Depends(get_db)):
    await _project_or_404(db, project_id)
    row = await db.get(ChangoverClipDB, row_id)
    if row is None or row.project_id != project_id or row.origin != "ai":
        raise HTTPException(status_code=404, detail="Transition not found")
    if row.status == "building" or _busy(project_id):
        raise HTTPException(status_code=409, detail="That transition is still being built")
    if not _source_url(row):
        raise HTTPException(status_code=409, detail="This transition can't be trimmed; regenerate it instead")
    if body.end - body.start < ait.MIN_TRIM_SECONDS:
        raise HTTPException(status_code=422, detail=f"Keep at least {ait.MIN_TRIM_SECONDS:g}s")
    row.status = "building"
    row.error_message = ""
    await db.commit()
    _spawn(_trim(project_id, row_id, body.start, body.end, body.drink_text))
    return _to_item(row)


async def _retext(project_id: int, row_id: int, drink_text: str) -> None:
    try:
        async with async_session() as session:
            await ait.retext_ai_transition(session, project_id, row_id, drink_text)
    except Exception as exc:
        logger.error("Changing the text of AI transition %s failed: %s", row_id, exc)
        async with async_session() as session:
            row = await session.get(ChangoverClipDB, row_id)
            if row is not None and row.status == "building":
                row.status = "error"
                row.error_message = str(exc)[:500]
                await session.commit()


@router.post("/{project_id}/{row_id}/text", status_code=202)
async def set_ai_transition_text(project_id: int, row_id: int, body: TextRequest, db: AsyncSession = Depends(get_db)):
    """Rebuild one transition with the user's own call word (same clip range / same art)."""
    await _project_or_404(db, project_id)
    row = await db.get(ChangoverClipDB, row_id)
    if row is None or row.project_id != project_id or row.origin != "ai":
        raise HTTPException(status_code=404, detail="Transition not found")
    if row.status == "building" or _busy(project_id):
        raise HTTPException(status_code=409, detail="That transition is still being built")
    if row.source_type == "ai_youtube" and not _source_url(row):
        raise HTTPException(status_code=409, detail="This video's source is gone (already rendered); regenerate it instead")
    row.status = "building"
    row.error_message = ""
    await db.commit()
    _spawn(_retext(project_id, row_id, body.drink_text))
    return _to_item(row)


@router.post("/{project_id}/add", status_code=202)
async def add_ai_transition(project_id: int, body: RegenerateRequest, db: AsyncSession = Depends(get_db)):
    project = await _project_or_404(db, project_id)
    if _busy(project_id):
        raise HTTPException(status_code=409, detail="Transitions are already being generated")
    row_id = await ait.add_ai_transition_row(db, project_id, body.kind or "card")
    if row_id is None:
        raise HTTPException(status_code=409, detail=f"At most {ait.MAX_COUNT} transitions")
    _spawn(_regenerate(project_id, row_id, _theme(project), body.prompt, body.kind, body.drink_text))
    return {"id": row_id}


@router.delete("/{project_id}/{row_id}")
async def delete_ai_transition(project_id: int, row_id: int, db: AsyncSession = Depends(get_db)):
    row = await db.get(ChangoverClipDB, row_id)
    if row is not None and row.status == "building":
        raise HTTPException(status_code=409, detail="That transition is still being built")
    if not await ait.delete_ai_transition(db, project_id, row_id):
        raise HTTPException(status_code=404, detail="Transition not found")
    return {"status": "deleted"}
