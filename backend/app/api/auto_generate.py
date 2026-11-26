"""AI auto-generate proposal and approval endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.schemas import (
    AiSessionResponse,
    AiSessionState,
    AutoGenerateApprovalResponse,
    AutoGenerateJobProgressResponse,
    AutoGenerateProjectResponse,
    AutoGenerateProposalApproveRequest,
    AutoGenerateProposalCreate,
    AutoGenerateProposalJobStartResponse,
    AutoGenerateProposalJobStatusResponse,
    AutoGenerateProposalLockRequest,
    AutoGenerateProposalReplaceRequest,
    AutoGenerateProposalResponse,
    AutoGenerateProposalReviseRequest,
    AutoGenerateReplaceJobStartResponse,
    AutoGenerateReviseJobStartResponse,
    ChangoverClipDB,
    ClipDB,
    ClipStatus,
    ProjectDB,
    RenderDB,
)
from app.services.changeover import ensure_default_changeover
from app.services.auto_generate import (
    AiTransitionRequest,
    ai_session_store,
    create_auto_generate_job,
    job_store,
    job_to_response,
    proposal_job_store,
    proposal_job_to_response,
    proposal_to_response,
    proposal_store,
    start_auto_process_queue,
    start_proposal_job,
    start_replace_job,
    start_revise_job,
)

router = APIRouter(prefix="/api/auto-generate", tags=["auto-generate"])
PROPOSAL_FAILURE_MESSAGE = "AI playlist generation failed."
APPROVAL_FAILURE_MESSAGE = "AI playlist approval failed."


@router.post("/proposals", response_model=AutoGenerateProposalJobStartResponse)
async def create_proposal(payload: AutoGenerateProposalCreate):
    """Start a background AI proposal generation job and return its ID immediately."""
    try:
        job = await start_proposal_job(payload.prompt, mode=payload.effective_mode)
        return AutoGenerateProposalJobStartResponse(proposal_job_id=job.job_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=PROPOSAL_FAILURE_MESSAGE) from exc


@router.get("/proposal-jobs/{job_id}", response_model=AutoGenerateProposalJobStatusResponse)
async def get_proposal_job(job_id: str):
    """Poll the status of a pending proposal generation or replace job."""
    job = await proposal_job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Proposal job not found or expired")
    proposal = None
    if job.status == "complete" and job.proposal_id:
        proposal = await proposal_store.get(job.proposal_id)
    return proposal_job_to_response(job, proposal)


@router.post("/proposals/{proposal_id}/replace", response_model=AutoGenerateReplaceJobStartResponse)
async def replace_proposal_item(proposal_id: str, payload: AutoGenerateProposalReplaceRequest):
    """Start a background slot replacement job and return its ID immediately."""
    proposal = await proposal_store.get(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found or expired")
    if payload.slot_index >= len(proposal.items):
        raise HTTPException(status_code=400, detail="No such slot")
    if proposal.items[payload.slot_index].locked:
        raise HTTPException(status_code=409, detail="That slot is locked. Unlock it to swap it.")
    try:
        job = await start_replace_job(proposal_id, payload.slot_index, note=payload.note)
        return AutoGenerateReplaceJobStartResponse(replace_job_id=job.job_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=PROPOSAL_FAILURE_MESSAGE) from exc


@router.post("/proposals/{proposal_id}/revise", response_model=AutoGenerateReviseJobStartResponse)
async def revise_proposal(proposal_id: str, payload: AutoGenerateProposalReviseRequest):
    """Start a background REVISE: the AI swaps only the unlocked slots the comment calls for.
    Poll it like a proposal job (/proposal-jobs/{id})."""
    proposal = await proposal_store.get(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found or expired")
    if not payload.comment.strip():
        raise HTTPException(status_code=400, detail="Say what to change")
    try:
        job = await start_revise_job(proposal_id, payload.comment)
        return AutoGenerateReviseJobStartResponse(revise_job_id=job.job_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=PROPOSAL_FAILURE_MESSAGE) from exc


@router.post("/proposals/{proposal_id}/undo", response_model=AutoGenerateProposalResponse)
async def undo_proposal_revision(proposal_id: str):
    """Restore the playlist from before the latest REVISE (one step)."""
    if not await proposal_store.get(proposal_id):
        raise HTTPException(status_code=404, detail="Proposal not found or expired")
    proposal = await proposal_store.undo_revision(proposal_id)
    if not proposal:
        raise HTTPException(status_code=409, detail="Nothing to undo")
    return proposal_to_response(proposal)


@router.post("/proposals/{proposal_id}/lock", response_model=AutoGenerateProposalResponse)
async def lock_proposal_slot(proposal_id: str, payload: AutoGenerateProposalLockRequest):
    """Lock (or unlock) a slot so REVISE and REPLACE leave it alone."""
    proposal = await proposal_store.set_locked(proposal_id, payload.slot_index, payload.locked)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal or slot not found")
    return proposal_to_response(proposal)


async def _create_project_and_clips(
    db: AsyncSession, proposal, project_name: str
) -> tuple[int, list[int]]:
    """Create the project + its pending clips from a resolved proposal.

    Shared by the /project endpoint (pre-approve, for custom-transition config) and
    approve() (when no project was pre-created).
    """
    project = ProjectDB(
        name=(project_name or proposal.normalized_prompt[:255]).strip() or "AI Power Hour",
        description=f"AI generated from prompt: {proposal.normalized_prompt}",
    )
    db.add(project)
    await db.flush()

    clips: list[ClipDB] = []
    for item in proposal.items:
        clip = ClipDB(
            project_id=project.id,
            position=item.slot_index,
            source_url=f"https://www.youtube.com/watch?v={item.youtube_id}",
            source_title=item.title,
            source_artist=item.artist,
            source_thumbnail=item.thumbnail,
            youtube_id=item.youtube_id,
            status=ClipStatus.PENDING,
        )
        db.add(clip)
        clips.append(clip)

    await db.flush()
    clip_ids = [clip.id for clip in clips]
    await db.commit()
    return project.id, clip_ids


async def _sync_pending_clips(db: AsyncSession, project_id: int, proposal) -> list[int]:
    """Make a pre-created project's clips match the proposal as approved.

    The project can be created early (to build a custom transition or review AI ones) and the
    user may still replace songs afterwards. While none of its clips has been processed, the
    clip rows are rebuilt from the proposal; otherwise the existing ones are kept."""
    rows = (
        await db.execute(select(ClipDB).where(ClipDB.project_id == project_id).order_by(ClipDB.position))
    ).scalars().all()
    wanted = [(item.youtube_id, item.slot_index) for item in proposal.items]
    current = [(clip.youtube_id, clip.position) for clip in rows]
    if current != wanted and all(clip.status == ClipStatus.PENDING for clip in rows):
        for clip in rows:
            await db.delete(clip)
        await db.flush()
        rows = []
        for item in proposal.items:
            clip = ClipDB(
                project_id=project_id,
                position=item.slot_index,
                source_url=f"https://www.youtube.com/watch?v={item.youtube_id}",
                source_title=item.title,
                source_artist=item.artist,
                source_thumbnail=item.thumbnail,
                youtube_id=item.youtube_id,
                status=ClipStatus.PENDING,
            )
            db.add(clip)
            rows.append(clip)
        await db.flush()
        await db.commit()
    return [clip.id for clip in rows]


@router.post("/proposals/{proposal_id}/project", response_model=AutoGenerateProjectResponse)
async def create_project_for_proposal(
    proposal_id: str,
    payload: AutoGenerateProposalApproveRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create the project + clips for a proposal WITHOUT starting processing.

    Lets the user configure a custom transition clip against a real project id
    before approving. approve() then reuses this project (passed back as project_id).
    """
    proposal = await proposal_store.get(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found or expired")

    unresolved = [item for item in proposal.items if item.status != "resolved"]
    if unresolved:
        raise HTTPException(status_code=400, detail="Proposal still has unresolved songs")

    try:
        project_id, clip_ids = await _create_project_and_clips(db, proposal, payload.project_name)
        return AutoGenerateProjectResponse(project_id=project_id, clip_ids=clip_ids)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=APPROVAL_FAILURE_MESSAGE) from exc


@router.post("/proposals/{proposal_id}/approve", response_model=AutoGenerateApprovalResponse)
async def approve_proposal(
    proposal_id: str,
    payload: AutoGenerateProposalApproveRequest,
    db: AsyncSession = Depends(get_db),
):
    """Approve an AI proposal and start processing.

    Reuses a pre-created project when ``project_id`` is supplied (custom-transition
    flow); otherwise creates the project + clips. When ``include_transition`` is set
    and no custom changeover was configured, builds the default "SHOT!" card.
    """
    proposal = await proposal_store.get(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found or expired")

    unresolved = [item for item in proposal.items if item.status != "resolved"]
    if unresolved:
        raise HTTPException(status_code=400, detail="Proposal still has unresolved songs")

    try:
        if payload.project_id is not None:
            # Reuse the project the frontend pre-created for a custom transition.
            project = await db.get(ProjectDB, payload.project_id)
            if project is None:
                raise HTTPException(status_code=404, detail="Project not found")
            # Guard: never reuse a project that has already been rendered, so we can't
            # re-process or clobber an existing finished project.
            existing_render = await db.execute(
                select(RenderDB.id).where(RenderDB.project_id == project.id).limit(1)
            )
            if existing_render.scalar_one_or_none() is not None:
                raise HTTPException(status_code=409, detail="Project already has a render; cannot reuse")
            project_id = project.id
            clip_ids = await _sync_pending_clips(db, project_id, proposal)
        else:
            project_id, clip_ids = await _create_project_and_clips(db, proposal, payload.project_name)

        # A custom (manual) changeover always wins. Otherwise either let the AI create a
        # varied set of transitions (built just before rendering), or fall back to the
        # default 3·2·1 → "SHOT!" card.
        ai_transitions = None
        if payload.include_transition:
            manual = await db.execute(
                select(ChangoverClipDB.id)
                .where(ChangoverClipDB.project_id == project_id, ChangoverClipDB.origin == "manual")
                .limit(1)
            )
            has_manual = manual.scalar_one_or_none() is not None
            reviewed = await db.execute(
                select(ChangoverClipDB.id)
                .where(
                    ChangoverClipDB.project_id == project_id,
                    ChangoverClipDB.origin == "ai",
                    ChangoverClipDB.status == "ready",
                )
                .limit(1)
            )
            has_reviewed = reviewed.scalar_one_or_none() is not None
            if payload.ai_transitions_reviewed and has_reviewed and not has_manual:
                pass  # keep the transitions the user reviewed; the render cycles through them
            elif payload.ai_transition_count > 0 and not has_manual and not payload.ai_transitions_reviewed:
                ai_transitions = AiTransitionRequest(
                    theme=proposal.prompt,
                    count=payload.ai_transition_count,
                    sources=payload.ai_transition_sources,
                    prompt=payload.ai_transition_prompt,
                    drink_text=payload.ai_transition_text,
                )
            else:
                if payload.ai_transitions_reviewed:
                    # Reviewed, but nothing usable was left: clear the leftovers so the
                    # default card is built (it only fills a project without transitions).
                    await db.execute(
                        delete(ChangoverClipDB).where(
                            ChangoverClipDB.project_id == project_id, ChangoverClipDB.origin == "ai"
                        )
                    )
                    await db.commit()
                await ensure_default_changeover(db, project_id)

        job = await create_auto_generate_job(project_id, len(clip_ids))
        start_auto_process_queue(job.job_id, project_id, clip_ids, transitions=ai_transitions)
        # The draft is now a running build: clear it so no device offers to resume it.
        await ai_session_store.reset()
        return AutoGenerateApprovalResponse(project_id=project_id, job_id=job.job_id, clip_ids=clip_ids)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=APPROVAL_FAILURE_MESSAGE) from exc


async def _session_response() -> AiSessionResponse:
    state, version, updated_at = await ai_session_store.get()
    proposal = await proposal_store.get(state.proposal_id) if state.proposal_id else None
    active = await job_store.active()
    return AiSessionResponse(
        session=state,
        version=version,
        updated_at=updated_at,
        proposal=proposal_to_response(proposal) if proposal else None,
        active_job=job_to_response(active) if active else None,
    )


@router.get("/session", response_model=AiSessionResponse)
async def get_ai_session():
    """The shared AI draft plus its proposal and any running build, for whichever device asks."""
    return await _session_response()


@router.put("/session", response_model=AiSessionResponse)
async def put_ai_session(payload: AiSessionState):
    """Replace the shared AI draft (the last device to write wins)."""
    await ai_session_store.put(payload)
    return await _session_response()


@router.delete("/session", response_model=AiSessionResponse)
async def clear_ai_session():
    await ai_session_store.reset()
    return await _session_response()


# Declared before /jobs/{job_id} so "active" isn't read as a job id.
@router.get("/jobs/active", response_model=Optional[AutoGenerateJobProgressResponse])
async def get_active_auto_generate_job():
    """The running AI build, if any, so a second device can find it without knowing its id."""
    job = await job_store.active()
    return job_to_response(job) if job else None


@router.get("/jobs/{job_id}", response_model=AutoGenerateJobProgressResponse)
async def get_auto_generate_job(job_id: str):
    """Fetch background progress for an approved AI auto-generate run."""
    job = await job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Auto-generate job not found or expired")
    return job_to_response(job)
