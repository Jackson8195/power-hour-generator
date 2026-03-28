"""Project CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.clip_utils import remove_clip_analysis, serialize_clip
from app.core.database import get_db
from app.core.config import settings
from app.core.security import unlink_managed_file
from app.models.schemas import (
    ProjectDB, ClipDB, ProjectCreate, ProjectResponse, ProjectDetail,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("/", response_model=list[ProjectResponse])
async def list_projects(db: AsyncSession = Depends(get_db)):
    """List all projects with clip counts."""
    result = await db.execute(
        select(
            ProjectDB,
            func.count(ClipDB.id).label("clip_count"),
        )
        .outerjoin(ClipDB)
        .group_by(ProjectDB.id)
        .order_by(ProjectDB.updated_at.desc())
    )

    projects = []
    for row in result.all():
        project = row[0]
        proj_dict = ProjectResponse.model_validate(project)
        proj_dict.clip_count = row[1]
        projects.append(proj_dict)

    return projects


@router.post("/", response_model=ProjectResponse)
async def create_project(project: ProjectCreate, db: AsyncSession = Depends(get_db)):
    """Create a new Power Hour project."""
    db_project = ProjectDB(
        name=project.name,
        description=project.description,
        clip_duration=project.clip_duration,
        transition_type=project.transition_type,
    )
    db.add(db_project)
    await db.flush()
    await db.refresh(db_project)
    return db_project


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: int, db: AsyncSession = Depends(get_db)):
    """Get project details with all clips."""
    result = await db.execute(
        select(ProjectDB)
        .options(selectinload(ProjectDB.clips))
        .where(ProjectDB.id == project_id)
    )
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    detail = ProjectDetail.model_validate(project)
    detail.clips = [serialize_clip(clip) for clip in sorted(project.clips, key=lambda c: c.position)]
    detail.clip_count = len(detail.clips)
    return detail


@router.delete("/{project_id}")
async def delete_project(project_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a project and all its clips."""
    result = await db.execute(
        select(ProjectDB)
        .options(selectinload(ProjectDB.clips))
        .where(ProjectDB.id == project_id)
    )
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    for clip in project.clips:
        if clip.file_path:
            unlink_managed_file(clip.file_path, settings.media_dir)
        remove_clip_analysis(clip.id)

    await db.delete(project)
    return {"status": "deleted", "project_id": project_id}
