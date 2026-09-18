from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Video AI Studio"
    app_env: str = "production"
    app_secret_key: str = Field(min_length=32)
    app_encryption_key: str = Field(min_length=32)
    access_token_minutes: int = 720

    admin_username: str = "admin"
    admin_password: str = Field(min_length=12)

    database_url: str = "sqlite:///./video_ai.db"
    data_dir: Path = Path("./data")

    queue_mode: str = "celery"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    asr_model: str = "small"
    asr_device: str = "cpu"
    asr_compute_type: str = "int8"
    asr_cpu_threads: int = 0

    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    ytdlp_cookies_file: str | None = None
    playwright_browser_executable: str | None = None
    playwright_profile_dir: Path | None = None
    playwright_timeout_seconds: int = 90000
    douyin_login_timeout_seconds: int = 180
    download_max_height: int = 1080
    max_video_duration_seconds: int = 14400
    max_download_bytes: int = 8589934592
    keep_source_media: bool = False

    # Network timeouts protect against an unresponsive provider. Generation
    # length is intentionally left to the configured LLM provider.
    llm_timeout_seconds: int = 300
    llm_max_chunk_chars: int = 12000

    assistant_max_context_chars: int = Field(default=40000, ge=4000, le=160000)
    assistant_history_chars: int = Field(default=24000, ge=2000, le=100000)
    assistant_run_lease_seconds: int = Field(default=900, ge=60)
    assistant_max_wait_seconds: int = Field(default=21600, ge=60)
    assistant_max_resources: int = Field(default=20, ge=1, le=100)
    assistant_web_api_key: str = ""
    assistant_vision_model: str = ""
    assistant_vision_base_url: str = ""
    assistant_vision_api_key: str = ""
    assistant_capture_frames: bool = False
    assistant_max_frames: int = Field(default=6, ge=1, le=12)
    assistant_agent_max_steps: int = Field(default=4, ge=1, le=6)

    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "jobs").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "uploads").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "creators").mkdir(parents=True, exist_ok=True)
        self.douyin_profile_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    @property
    def douyin_profile_dir(self) -> Path:
        return self.playwright_profile_dir or (self.data_dir / "playwright" / "douyin")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
