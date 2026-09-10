from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=512)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    username: str


class LLMSettingsIn(BaseModel):
    provider: str = Field(default="deepseek", max_length=80)
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=2000)
    clear_api_key: bool = False
    temperature: float = Field(default=0.2, ge=0, le=2)
    custom_prompt: str | None = Field(default=None, max_length=8000)


class LLMSettingsOut(BaseModel):
    provider: str
    base_url: str
    model: str
    api_key_configured: bool
    api_key_masked: str | None
    temperature: float
    custom_prompt: str | None


class LLMTestResponse(BaseModel):
    ok: bool
    message: str


class StorageStats(BaseModel):
    data_dir: str
    total_bytes: int
    jobs_bytes: int
    uploads_bytes: int
    models_bytes: int
    temporary_bytes: int
    disk_free_bytes: int
    removable_temporary_bytes: int


class VideoPreviewRequest(BaseModel):
    source_url: HttpUrl


class VideoPreviewResponse(BaseModel):
    source_url: str
    platform: str
    title: str
    uploader: str | None = None
    duration: float | None = None
    thumbnail: str | None = None
    extractor: str | None = None


SummaryPreset = Literal[
    "standard",
    "detailed",
    "course",
    "meeting",
    "interview",
    "knowledge",
    "short_copy",
    "transcript",
    "custom",
]


class TaskDefaults(BaseModel):
    asr_model: Literal["tiny", "base", "small", "medium", "large-v3"] = "small"
    language: str = Field(default="", max_length=20)
    summary_enabled: bool = True
    summary_preset: SummaryPreset = "standard"
    summary_depth: Literal["brief", "standard", "detailed"] = "standard"


class JobCreate(BaseModel):
    source_url: HttpUrl
    language: str | None = Field(default=None, max_length=20)
    asr_model: Literal["tiny", "base", "small", "medium", "large-v3"] | None = None
    summary_enabled: bool = True
    summary_language: str = Field(default="Chinese", max_length=40)
    summary_preset: SummaryPreset = "standard"
    summary_instruction: str | None = Field(default=None, max_length=4000)


class JobResummarizeRequest(BaseModel):
    summary_language: str = Field(default="Chinese", max_length=40)
    summary_preset: SummaryPreset = "standard"
    summary_instruction: str | None = Field(default=None, max_length=4000)


class TranscriptSegmentUpdate(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str = Field(min_length=1, max_length=12000)


class TranscriptUpdateRequest(BaseModel):
    segments: list[TranscriptSegmentUpdate] = Field(min_length=1, max_length=20000)


class JobResponse(BaseModel):
    id: str
    source_url: str
    source_type: str
    source_filename: str | None
    platform: str | None
    title: str | None
    status: str
    stage: str
    progress: int
    language: str | None
    asr_model: str | None
    summary_enabled: bool
    summary_language: str
    summary_preset: str
    summary_instruction: str | None
    summary_excerpt: str | None
    error_code: str | None
    error_message: str | None
    metadata: dict[str, Any] | None
    artifacts: dict[str, str]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class JobResultResponse(BaseModel):
    source_url: str
    platform: str
    title: str
    metadata: dict[str, Any]
    transcript: dict[str, Any]
    summary: str | None


class HealthResponse(BaseModel):
    status: str
    ffmpeg: bool
    ffprobe: bool
    ytdlp: bool
    database: bool
    data_dir_writable: bool
    queue_mode: str
    queue: bool
