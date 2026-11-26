"""Database models and API schemas."""

import enum
from datetime import datetime
from typing import Literal, Optional

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

# Long, descriptive AI playlist prompts (themes, seasons, examples, transition guidance) are
# the point of the feature, so the limit is generous. The frontend textarea mirrors it.
PROMPT_MAX_LENGTH = 4000

class SearchQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    max_results: int = Field(default=10, ge=1, le=50)
    project_id: Optional[int] = None
    # False = plain YouTube search (no music-category filter / suffix / ranking),
    # used for transition (changeover) clip searches.
    music: bool = True


class SearchResult(BaseModel):
    youtube_id: str
    title: str
    artist: str = ""
    thumbnail: str
    duration: str = ""
    view_count: str = ""
    search_source: str = ""
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
    file_missing: bool = False

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
    # After a successful render, trim every clip still on its full source to its saved range
    # and delete the sources (the AI build's review flow). Off: sources are left as they are.
    finalize_sources: bool = False


class RenderProgress(BaseModel):
    render_id: int
    status: RenderStatus
    progress: float
    output_path: str = ""
    error_message: str = ""
    gpu_active: bool = False  # True when this render is using GPU (NVENC) encoding


class RenderLibraryEntry(BaseModel):
    render_id: int
    project_id: int
    project_name: str
    output_url: str
    # Same file, served as an attachment so other devices save it.
    download_url: str = ""
    size_bytes: int = 0
    completed_at: Optional[datetime] = None


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


# ─── Changeover Clip ─────────────────────────────────────

class ChangoverClipDB(Base):
    __tablename__ = "changover_clips"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    # A project has at most one "manual" (user-configured) changeover and any number of
    # "ai" ones, which the renderer cycles through in ``position`` order.
    project_id    = Column(Integer, ForeignKey("projects.id"), nullable=False)
    origin        = Column(String(10), default="manual", nullable=False)  # manual | ai
    position      = Column(Integer, default=0, nullable=False)
    label         = Column(String(100), default="")
    source_type   = Column(String(20), default="image_audio")  # image_audio | youtube | local_video | default_shot | ai_card | ai_youtube
    youtube_id    = Column(String(50), default="")
    image_path    = Column(String(500), default="")
    audio_path    = Column(String(500), default="")
    raw_video_path = Column(String(500), default="")   # pre-trim downloaded/uploaded video
    output_path   = Column(String(500), default="")    # pre-built .mp4
    duration      = Column(Float, default=3.0)
    trim_start    = Column(Float, default=0.0)
    trim_end      = Column(Float, default=0.0)
    style         = Column(Text, default="")  # AI rows: JSON {text_color, hit_text, sound} for re-trims
    status        = Column(String(50), default="pending")  # pending | downloading | downloaded | ready | error
    error_message = Column(Text, default="")
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChangoverClipResponse(BaseModel):
    id: int
    project_id: int
    source_type: str
    youtube_id: str
    image_path: str
    audio_path: str
    raw_video_path: str
    output_path: str
    duration: float
    trim_start: float
    trim_end: float
    status: str
    error_message: str
    preview_url: str = ""
    raw_video_url: str = ""
    origin: str = "manual"
    position: int = 0
    label: str = ""
    model_config = {"from_attributes": True}


class AutoGenerateProposalCreate(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=PROMPT_MAX_LENGTH)
    # "music"  = songs only (music-category search + ranking)
    # "videos" = plain YouTube videos, no music assumptions
    # "mixed"  = the AI picks songs and non-music clips per slot, each resolved its own way
    mode: Optional[Literal["music", "videos", "mixed"]] = None
    # Deprecated: older clients send a boolean. Used only when ``mode`` is omitted.
    music: bool = True

    @property
    def effective_mode(self) -> str:
        return self.mode or ("music" if self.music else "videos")


class AutoGenerateProposalReplaceRequest(BaseModel):
    slot_index: int = Field(..., ge=0, lt=60)
    # Optional steer for this one slot: a comment ("something funnier"), an exact
    # "Artist - Title", or a YouTube link (used as-is).
    note: str = Field(default="", max_length=300)


class AutoGenerateProposalReviseRequest(BaseModel):
    """A general comment on the whole playlist; only the slots it calls for are swapped."""
    comment: str = Field(..., min_length=3, max_length=1000)


class AutoGenerateProposalLockRequest(BaseModel):
    slot_index: int = Field(..., ge=0, lt=60)
    locked: bool


class AutoGenerateProposalApproveRequest(BaseModel):
    project_name: str = Field(default="", max_length=255)
    # When the user configured a custom transition, the frontend pre-creates the
    # project (via the /project endpoint) and passes its id here so approve reuses it
    # instead of creating a fresh one.
    project_id: Optional[int] = None
    # Insert a transition between songs. If no custom changeover was configured, a
    # default 3·2·1 → "SHOT!" card is built at approve time.
    include_transition: bool = True
    # Let the AI create its own transition clips (instead of the default card) and cycle
    # through them between songs. 0 = off. Ignored if a custom transition already exists.
    ai_transition_count: int = Field(default=0, ge=0, le=8)
    # "cards" = drink-art cards, "youtube" = found clips, "both" = a mix.
    ai_transition_sources: Literal["cards", "youtube", "both"] = "both"
    # The user already generated and reviewed the AI transitions in the pre-created project
    # (/api/ai-transitions): keep them instead of generating new ones during the build.
    ai_transitions_reviewed: bool = False
    # The user's direction for AI transitions generated during the build.
    ai_transition_prompt: str = Field(default="", max_length=1000)
    # The user's call word for AI transitions generated during the build (None: the AI picks).
    ai_transition_text: Optional[str] = Field(default=None, max_length=48)


class AiSessionState(BaseModel):
    """The AI generator's in-progress draft, kept on the server so another device (e.g. the
    phone) can pick it up mid-way. One per app: this is a single-user local tool."""

    prompt: str = Field(default="", max_length=PROMPT_MAX_LENGTH)
    mode: Literal["music", "videos", "mixed"] = "music"
    project_name: str = Field(default="", max_length=255)
    proposal_id: str = Field(default="", max_length=64)
    # A playlist being generated right now (any device can keep polling it).
    proposal_job_id: str = Field(default="", max_length=64)
    transition_mode: Literal["default", "ai", "custom"] = "default"
    ai_transition_count: int = Field(default=4, ge=1, le=8)
    ai_transition_sources: Literal["cards", "youtube", "both"] = "both"
    transition_project_id: Optional[int] = None
    transition_prompt: str = Field(default="", max_length=1000)
    drink_text: str = Field(default="DRINK!", max_length=48)
    # A REVISE running on the playlist (either device shows it and picks up the result).
    revise_job_id: str = Field(default="", max_length=64)


class AiSessionResponse(BaseModel):
    session: AiSessionState
    # Bumped on every write so a device can tell its copy is stale.
    version: int
    updated_at: datetime
    proposal: Optional["AutoGenerateProposalResponse"] = None
    active_job: Optional["AutoGenerateJobProgressResponse"] = None


class AutoGenerateProjectResponse(BaseModel):
    project_id: int
    clip_ids: list[int]


class AutoGenerateProposalItem(BaseModel):
    slot_index: int
    requested_title: str
    requested_artist: str
    youtube_id: str = ""
    title: str = ""
    artist: str = ""
    thumbnail: str = ""
    duration: str = ""
    resolution_source: str = ""
    reason: str = ""
    status: str = "resolved"
    # "song" is resolved with music search/ranking, "clip" with a plain YouTube search.
    kind: Literal["song", "clip"] = "song"
    # Slots that share a youtube_id are cut from one (compilation) video: segment_index is this
    # slot's part (0-based) and segment_count how many slots use that video. Recomputed by the
    # backend whenever the proposal changes; 0 / 1 for an ordinary single-clip slot.
    segment_index: int = 0
    segment_count: int = 1
    # Locked slots are never touched by REVISE or REPLACE.
    locked: bool = False
    # Swapped in by the latest REVISE (shown as NEW until the next one).
    revised: bool = False


class AutoGenerateProposalResponse(BaseModel):
    proposal_id: str
    normalized_prompt: str
    items: list[AutoGenerateProposalItem]
    unresolved_count: int
    expires_at: datetime
    mode: Literal["music", "videos", "mixed"] = "music"
    # Every REVISE comment so far; they also steer later swaps.
    notes: list[str] = []
    # True while the list from before the latest REVISE can still be restored.
    can_undo: bool = False


class AutoGenerateApprovalResponse(BaseModel):
    project_id: int
    job_id: str
    clip_ids: list[int]


class AutoGenerateJobProgressResponse(BaseModel):
    job_id: str
    project_id: int
    phase: str
    progress: float
    total_clips: int
    processed_clips: int
    current_step: str = ""
    current_title: str = ""
    current_artist: str = ""
    render_id: Optional[int] = None
    output_path: str = ""
    error_message: str = ""
    gpu_active: bool = False
    updated_at: datetime


class AutoGenerateProposalJobStartResponse(BaseModel):
    proposal_job_id: str


class AutoGenerateProposalJobStatusResponse(BaseModel):
    job_id: str
    status: str
    error_message: str = ""
    proposal: Optional[AutoGenerateProposalResponse] = None
    updated_at: datetime


class AutoGenerateReplaceJobStartResponse(BaseModel):
    replace_job_id: str


class AutoGenerateReviseJobStartResponse(BaseModel):
    revise_job_id: str


# AiSessionResponse refers to response models declared after it.
AiSessionResponse.model_rebuild()
