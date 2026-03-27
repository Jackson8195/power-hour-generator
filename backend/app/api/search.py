"""YouTube search endpoints."""

from fastapi import APIRouter, HTTPException

from app.models.schemas import SearchQuery, SearchResult
from app.services.youtube import search_youtube

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("/youtube", response_model=list[SearchResult])
async def search(query: SearchQuery):
    """Search YouTube for music videos."""
    try:
        results = await search_youtube(query.query, query.max_results)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
