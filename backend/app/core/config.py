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
    # Model that reviews resolved YouTube results against the prompt (rejects off-topic videos).
    # Blank = use openai_model. It's one short call per batch, so a stronger model is cheap here.
    openai_review_model: str = ""
    # AI transition art (blank model = always use the bundled drink art). quality: low|medium|high.
    openai_image_model: str = "gpt-image-2"
    openai_image_quality: str = "medium"
    # ElevenLabs (sound effects for transition cues). Blank = not used.
    elevenlabs_api_key: str = ""

    # Paths
    media_dir: Path = Path("./media")
    render_dir: Path = Path("./media/renders")
    database_url: str = "sqlite+aiosqlite:///./power_hour.db"

    # Server
    backend_port: int = 8000
    frontend_port: int = 5173
    cors_origins: str = "http://localhost:5173"
    # This machine's LAN address (set by scripts/docker-up), so a page opened at localhost can
    # still give out tape links that another device on the Wi-Fi can open.
    lan_host: str = ""

    # FFmpeg
    ffmpeg_path: str = "ffmpeg"
    # GPU encoding, automatic by default. When true, each render does a tiny real NVENC test
    # encode and uses h264_nvenc only if it works; otherwise it falls back to libx264. So CPU-only
    # machines (e.g. Mac) just use the CPU. Set USE_NVENC=0 to force CPU encoding.
    use_nvenc: bool = True
    nvenc_preset: str = "p5"  # NVENC preset p1 (fastest) .. p7 (slowest); p5 ≈ x264 "medium"

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
        self.changeover_dir.mkdir(parents=True, exist_ok=True)

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

    @property
    def changeover_dir(self) -> Path:
        return self.media_dir / "changeover"


settings = Settings()
settings.ensure_dirs()
