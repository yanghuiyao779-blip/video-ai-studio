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
    download_max_height: int = 1080
    max_video_duration_seconds: int = 14400
    max_download_bytes: int = 8589934592
    keep_source_media: bool = False

    # Network timeouts protect against an unresponsive provider. Generation
    # length is intentionally left to the configured LLM provider.
    llm_timeout_seconds: int = 300
    llm_max_chunk_chars: int = 12000

    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "jobs").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "uploads").mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
