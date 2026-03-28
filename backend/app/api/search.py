"""YouTube search and recommendation endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.schemas import ProjectDB, SearchQuery, SearchResult
from app.services.youtube import recommend_for_project, search_youtube

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("/youtube", response_model=list[SearchResult])
async def search(query: SearchQuery, db: AsyncSession = Depends(get_db)):
    """Search YouTube for music videos."""
    try:
        preferred_artists: list[str] = []
        if query.project_id is not None:
            result = await db.execute(
                select(ProjectDB)
                .options(selectinload(ProjectDB.clips))
                .where(ProjectDB.id == query.project_id)
            )
            project = result.scalar_one_or_none()
            if project:
                preferred_artists = [clip.source_artist for clip in project.clips if clip.source_artist]

        results = await search_youtube(
            query.query,
            query.max_results,
            preferred_artists=preferred_artists,
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recommendations/{project_id}", response_model=list[SearchResult])
async def recommendations(
    project_id: int,
    max_results: int = 12,
    db: AsyncSession = Depends(get_db),
):
    """Recommend songs based on the project's growing set of chosen artists."""
    result = await db.execute(
        select(ProjectDB)
        .options(selectinload(ProjectDB.clips))
        .where(ProjectDB.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        return await recommend_for_project(project.clips, max_results=max_results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
