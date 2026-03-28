"""Casting and playback endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.security import is_allowed_cast_video_url
from app.services.casting import casting_service

router = APIRouter(prefix="/api/cast", tags=["cast"])
CAST_FAILURE_MESSAGE = "Casting failed."


class CastRequest(BaseModel):
    device_id: str
    video_url: str
    title: str = "Power Hour"


@router.get("/devices")
async def discover_devices():
    """Discover available casting devices on the network."""
    devices = await casting_service.discover_devices()
    return {"devices": devices}


@router.post("/play")
async def cast_video(request: CastRequest):
    """Cast a video to a device."""
    if not is_allowed_cast_video_url(request.video_url):
        raise HTTPException(status_code=400, detail="Only rendered videos from this app can be cast")

    try:
        result = await casting_service.cast_video(
            device_id=request.device_id,
            video_url=request.video_url,
            title=request.title,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail="Casting device not found") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=CAST_FAILURE_MESSAGE) from e


@router.post("/stop")
async def stop_casting():
    """Stop the active cast session."""
    result = await casting_service.stop_casting()
    return result
