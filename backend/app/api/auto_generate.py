"""AI auto-generate proposal and approval endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.schemas import (
    AutoGenerateApprovalResponse,
    AutoGenerateJobProgressResponse,
    AutoGenerateProposalApproveRequest,
    AutoGenerateProposalCreate,
    AutoGenerateProposalJobStartResponse,
    AutoGenerateProposalJobStatusResponse,
    AutoGenerateProposalReplaceRequest,
    AutoGenerateReplaceJobStartResponse,
    ClipDB,
    ClipStatus,
    ProjectDB,
)
from app.services.auto_generate import (
    create_auto_generate_job,
    job_store,
    job_to_response,
    proposal_job_store,
    proposal_job_to_response,
    proposal_store,
    start_auto_process_queue,
    start_proposal_job,
    start_replace_job,
)

router = APIRouter(prefix="/api/auto-generate", tags=["auto-generate"])
PROPOSAL_FAILURE_MESSAGE = "AI playlist generation failed."
APPROVAL_FAILURE_MESSAGE = "AI playlist approval failed."


@router.post("/proposals", response_model=AutoGenerateProposalJobStartResponse)
async def create_proposal(payload: AutoGenerateProposalCreate):
    """Start a background AI proposal generation job and return its ID immediately."""
    try:
        job = await start_proposal_job(payload.prompt)
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
    try:
        job = await start_replace_job(proposal_id, payload.slot_index)
        return AutoGenerateReplaceJobStartResponse(replace_job_id=job.job_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=PROPOSAL_FAILURE_MESSAGE) from exc


@router.post("/proposals/{proposal_id}/approve", response_model=AutoGenerateApprovalResponse)
async def approve_proposal(
    proposal_id: str,
    payload: AutoGenerateProposalApproveRequest,
    db: AsyncSession = Depends(get_db),
):
    """Approve an AI proposal and create a normal project + clips."""
    proposal = await proposal_store.get(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found or expired")

    unresolved = [item for item in proposal.items if item.status != "resolved"]
    if unresolved:
        raise HTTPException(status_code=400, detail="Proposal still has unresolved songs")

    try:
        project = ProjectDB(
            name=(payload.project_name or proposal.normalized_prompt[:255]).strip() or "AI Power Hour",
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

        job = await create_auto_generate_job(project.id, len(clip_ids))
        start_auto_process_queue(job.job_id, project.id, clip_ids)
        return AutoGenerateApprovalResponse(project_id=project.id, job_id=job.job_id, clip_ids=clip_ids)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=APPROVAL_FAILURE_MESSAGE) from exc


@router.get("/jobs/{job_id}", response_model=AutoGenerateJobProgressResponse)
async def get_auto_generate_job(job_id: str):
    """Fetch background progress for an approved AI auto-generate run."""
    job = await job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Auto-generate job not found or expired")
    return job_to_response(job)
