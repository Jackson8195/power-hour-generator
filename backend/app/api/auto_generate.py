"""AI auto-generate proposal and approval endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.schemas import (
    AutoGenerateApprovalResponse,
    AutoGenerateJobProgressResponse,
    AutoGenerateProposalApproveRequest,
    AutoGenerateProposalCreate,
    AutoGenerateProposalReplaceRequest,
    AutoGenerateProposalResponse,
    ClipDB,
    ClipStatus,
    ProjectDB,
)
from app.services.auto_generate import (
    create_auto_generate_job,
    create_playlist_proposal,
    job_store,
    job_to_response,
    proposal_store,
    proposal_to_response,
    replace_playlist_item,
    start_auto_process_queue,
)

router = APIRouter(prefix="/api/auto-generate", tags=["auto-generate"])


@router.post("/proposals", response_model=AutoGenerateProposalResponse)
async def create_proposal(payload: AutoGenerateProposalCreate):
    """Create an AI-generated playlist proposal."""
    try:
        proposal = await create_playlist_proposal(payload.prompt)
        return proposal_to_response(proposal)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/proposals/{proposal_id}/replace", response_model=AutoGenerateProposalResponse)
async def replace_proposal_item(proposal_id: str, payload: AutoGenerateProposalReplaceRequest):
    """Replace one AI-generated slot before approval."""
    proposal = await proposal_store.get(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found or expired")

    try:
        item = await replace_playlist_item(proposal, payload.slot_index)
        updated = await proposal_store.replace_item(proposal_id, payload.slot_index, item)
        if not updated:
            raise HTTPException(status_code=404, detail="Proposal not found or expired")
        return proposal_to_response(updated)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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


@router.get("/jobs/{job_id}", response_model=AutoGenerateJobProgressResponse)
async def get_auto_generate_job(job_id: str):
    """Fetch background progress for an approved AI auto-generate run."""
    job = await job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Auto-generate job not found or expired")
    return job_to_response(job)
