"""Casting and playback endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.casting import casting_service

router = APIRouter(prefix="/api/cast", tags=["cast"])


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
    try:
        result = await casting_service.cast_video(
            device_id=request.device_id,
            video_url=request.video_url,
            title=request.title,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
async def stop_casting():
    """Stop the active cast session."""
    result = await casting_service.stop_casting()
    return result
