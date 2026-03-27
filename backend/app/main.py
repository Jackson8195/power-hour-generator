"""Power Hour Studio — FastAPI Application."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import init_db
from app.api import search, downloads, clips, projects, render, cast

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    logger.info("🍺 Power Hour Studio starting up...")
    await init_db()
    settings.ensure_dirs()
    logger.info(f"   Media dir: {settings.media_dir.resolve()}")
    logger.info(f"   Render dir: {settings.render_dir.resolve()}")
    logger.info("   Database initialized")
    yield
    # Shutdown
    logger.info("Power Hour Studio shutting down.")


app = FastAPI(
    title="Power Hour Studio",
    description="Create Power Hour videos with smart clip selection and TV casting",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow the Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve rendered videos as static files
render_path = Path(settings.render_dir)
render_path.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(render_path.parent)), name="static")

# Also serve downloaded media for preview playback
media_path = Path(settings.media_dir)
media_path.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(media_path)), name="media")

# Register routers
app.include_router(search.router)
app.include_router(downloads.router)
app.include_router(clips.router)
app.include_router(projects.router)
app.include_router(render.router)
app.include_router(cast.router)


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": "0.1.0",
        "ffmpeg_path": settings.ffmpeg_path,
        "youtube_api_configured": bool(settings.youtube_api_key),
    }
