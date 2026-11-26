"""Power Hour Studio — FastAPI Application."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.version import APP_VERSION
from app.core.database import init_db
from app.core.recovery import recover_interrupted_jobs
from app.core.storage import migrate_storage_layout
from app.api import search, downloads, clips, projects, render, cast, auto_generate, changeover, ai_transitions

logging.basicConfig(level=logging.INFO)
# HTTP client request lines include full URLs, and YouTube Data API URLs carry the API key.
for _name in ("httpx", "httpx2", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    logger.info("🍺 Power Hour Studio starting up...")
    await init_db()
    settings.ensure_dirs()
    await migrate_storage_layout()
    await recover_interrupted_jobs()
    logger.info(f"   Media dir: {settings.media_dir.resolve()}")
    logger.info(f"   Render dir: {settings.render_dir.resolve()}")
    logger.info("   Database initialized")
    yield
    # Shutdown
    logger.info("Power Hour Studio shutting down.")


app = FastAPI(
    title="Power Hour Studio",
    description="Create Power Hour videos with smart clip selection and TV casting",
    version=APP_VERSION,
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
app.mount("/static", StaticFiles(directory=str(render_path)), name="static")

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
app.include_router(auto_generate.router)
app.include_router(changeover.router)
app.include_router(ai_transitions.router)


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": APP_VERSION,
        # LAN address + frontend port for links another device can open ("" = unknown).
        "lan_host": settings.lan_host,
        "frontend_port": settings.frontend_port,
    }


@app.get("/", include_in_schema=False)
async def root():
    """Redirect the backend root to the interactive docs."""
    return RedirectResponse(url="/docs")
