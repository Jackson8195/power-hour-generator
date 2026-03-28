"""Database models and API schemas."""

import enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


# ─── SQLAlchemy ORM Models ───────────────────────────────────────────

class ClipStatus(str, enum.Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    ANALYZING = "analyzing"
    READY = "ready"
    ERROR = "error"


class RenderStatus(str, enum.Enum):
    QUEUED = "queued"
    RENDERING = "rendering"
    COMPLETE = "complete"
    ERROR = "error"


class ProjectDB(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    clip_duration = Column(Integer, default=60)
    transition_type = Column(String(50), default="crossfade")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    clips = relationship("ClipDB", back_populates="project", cascade="all, delete-orphan")
    renders = relationship("RenderDB", back_populates="project", cascade="all, delete-orphan")


class ClipDB(Base):
    __tablename__ = "clips"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    position = Column(Integer, nullable=False)  # Order in the power hour (0-59)

    # Source info
    source_url = Column(String(500), default="")
    source_title = Column(String(500), default="")
    source_artist = Column(String(255), default="")
    source_thumbnail = Column(String(500), default="")
    youtube_id = Column(String(20), default="")

    # Local file
    file_path = Column(String(500), default="")
    duration = Column(Float, default=0.0)  # Duration of the current local media file

    # Clip selection (which 60s segment to use)
    start_time = Column(Float, default=0.0)
    end_time = Column(Float, default=60.0)

    # Audio analysis results
    suggested_start = Column(Float, nullable=True)  # librosa's suggested best segment
    bpm = Column(Float, nullable=True)
    energy = Column(Float, nullable=True)

    status = Column(Enum(ClipStatus), default=ClipStatus.PENDING)
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("ProjectDB", back_populates="clips")


class RenderDB(Base):
    __tablename__ = "renders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    output_path = Column(String(500), default="")
    status = Column(Enum(RenderStatus), default=RenderStatus.QUEUED)
    progress = Column(Float, default=0.0)  # 0-100
    resolution = Column(String(20), default="1280x720")
    error_message = Column(Text, default="")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("ProjectDB", back_populates="renders")


# ─── Pydantic Schemas (API layer) ────────────────────────────────────

class SearchQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    max_results: int = Field(default=10, ge=1, le=50)
    project_id: Optional[int] = None


class SearchResult(BaseModel):
    youtube_id: str
    title: str
    artist: str = ""
    thumbnail: str
    duration: str = ""
    view_count: str = ""
    match_score: float = 0.0
    recommendation_reason: str = ""


class ClipCreate(BaseModel):
    source_url: str
    source_title: str = ""
    source_artist: str = ""
    source_thumbnail: str = ""
    youtube_id: str = ""
    position: int = 0


class ClipUpdate(BaseModel):
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    position: Optional[int] = None


class ClipResponse(BaseModel):
    id: int
    project_id: int
    position: int
    source_title: str
    source_artist: str
    source_thumbnail: str
    youtube_id: str
    file_path: str
    duration: float
    start_time: float
    end_time: float
    suggested_start: Optional[float]
    bpm: Optional[float]
    energy: Optional[float]
    status: ClipStatus
    preview_url: str = ""
    has_selection: bool = False

    model_config = {"from_attributes": True}


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    clip_duration: int = 60
    transition_type: str = "crossfade"


class ProjectResponse(BaseModel):
    id: int
    name: str
    description: str
    clip_duration: int
    transition_type: str
    created_at: datetime
    updated_at: datetime
    clip_count: int = 0

    model_config = {"from_attributes": True}


class ProjectDetail(ProjectResponse):
    clips: list[ClipResponse] = []


class RenderRequest(BaseModel):
    resolution: str = "1280x720"
    transition_type: str = "crossfade"
    include_countdown: bool = True


class RenderProgress(BaseModel):
    render_id: int
    status: RenderStatus
    progress: float
    output_path: str = ""
    error_message: str = ""


class ClipHighlight(BaseModel):
    start: float
    end: float
    score: float
    label: str


class ClipAnalysisResponse(BaseModel):
    clip_id: int
    preview_url: str = ""
    duration: float = 0.0
    suggested_start: float = 0.0
    suggested_end: float = 0.0
    waveform: list[float] = []
    highlights: list[ClipHighlight] = []


class ClipCommitRequest(BaseModel):
    start_time: float = Field(..., ge=0)
    end_time: float = Field(..., gt=0)
