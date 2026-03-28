"""Application configuration loaded from environment variables."""

from pathlib import Path
from pydantic_settings import BaseSettings

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # API Keys
    youtube_api_key: str = ""
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"

    # Paths
    media_dir: Path = Path("./media")
    render_dir: Path = Path("./media/renders")
    database_url: str = "sqlite+aiosqlite:///./power_hour.db"

    # Server
    backend_port: int = 8000
    frontend_port: int = 5173
    cors_origins: str = "http://localhost:5173"

    # FFmpeg
    ffmpeg_path: str = "ffmpeg"

    # Download settings
    max_concurrent_downloads: int = 3
    default_video_quality: int = 720

    # Power Hour defaults
    clip_duration: int = 60  # seconds per clip
    total_clips: int = 60   # clips per power hour
    transition_duration: float = 1.5  # seconds for transition
    countdown_start: int = 55  # show countdown at this second

    model_config = {
        "env_file": str(BACKEND_DIR / ".env"),
        "env_file_encoding": "utf-8",
    }

    def ensure_dirs(self):
        """Create media and render directories if they don't exist."""
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.analysis_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.render_dir.mkdir(parents=True, exist_ok=True)

    @property
    def downloads_dir(self) -> Path:
        return self.media_dir / "downloads"

    @property
    def clips_dir(self) -> Path:
        return self.media_dir / "clips"

    @property
    def analysis_dir(self) -> Path:
        return self.media_dir / "analysis"

    @property
    def temp_dir(self) -> Path:
        return self.media_dir / "temp"


settings = Settings()
settings.ensure_dirs()
