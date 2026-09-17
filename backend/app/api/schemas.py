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
    embedding_model: str = Field(default="", max_length=200)


class LLMSettingsOut(BaseModel):
    provider: str
    base_url: str
    model: str
    api_key_configured: bool
    api_key_masked: str | None
    temperature: float
    custom_prompt: str | None
    embedding_model: str


class CreatorAskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=8000)
    top_k: int = Field(default=6, ge=1, le=12)


class LLMTestResponse(BaseModel):
    ok: bool
    message: str


class StorageStats(BaseModel):
    data_dir: str
    total_bytes: int
    task_results_bytes: int
    jobs_bytes: int
    uploads_bytes: int
    creator_artifacts_bytes: int
    rag_index_bytes: int
    playwright_profile_bytes: int
    models_bytes: int
    temporary_bytes: int
    disk_free_bytes: int
    removable_temporary_bytes: int
    freed_temporary_bytes: int = 0
    measured_at: datetime


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


class CreatorCreate(BaseModel):
    profile_url: HttpUrl
    name: str | None = Field(default=None, max_length=500)


class CreatorPreviewResponse(BaseModel):
    platform: str
    source_url: str
    canonical_url: str
    sec_user_id: str
    uid: str | None
    nickname: str | None
    resolution_method: str
    source_video_id: str | None


class CreatorVideoImport(BaseModel):
    urls: list[HttpUrl] = Field(min_length=1, max_length=1000)


class CreatorResponse(BaseModel):
    id: str
    platform: str
    profile_url: str
    platform_creator_id: str | None
    name: str | None
    avatar_url: str | None
    status: str
    last_synced_at: datetime | None
    video_count: int = 0
    transcript_count: int = 0
    insight_count: int = 0
    created_at: datetime
    updated_at: datetime


class CreatorVideoResponse(BaseModel):
    id: str
    video_url: str
    title: str | None
    platform_video_id: str
    duration: int | None
    job_id: str | None
    job_status: str | None
    ingest_status: str
    insight_status: str | None


class CreatorAnalysisResponse(BaseModel):
    id: str
    creator_id: str
    status: str
    prompt_version: str
    input_snapshot: dict[str, Any]
    profile: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class CreatorSkillResponse(BaseModel):
    id: str
    creator_id: str
    analysis_run_id: str
    version: int
    status: str
    created_at: datetime
    download_url: str


class CreatorSyncRunResponse(BaseModel):
    id: str
    status: str
    discovered_count: int
    created_count: int
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class CreatorSkillSummary(BaseModel):
    id: str
    version: int
    status: str
    created_at: datetime
    download_url: str


class CreatorResearchStart(BaseModel):
    batch_size: int = Field(default=3, ge=1, le=10)
    auto_continue: bool = False
    target_video_limit: int | None = Field(default=10, ge=1, le=10000)
    failure_threshold_percent: int | None = Field(default=20, ge=1, le=100)


class CreatorResearchControls(BaseModel):
    """Mutable safety controls for a running creator research job."""
    batch_size: int | None = Field(default=None, ge=1, le=10)
    auto_continue: bool | None = None
    target_video_limit: int | None = Field(default=None, ge=1, le=10000)
    failure_threshold_percent: int | None = Field(default=None, ge=1, le=100)


class CreatorResearchRunResponse(BaseModel):
    id: str
    creator_id: str
    status: str
    batch_size: int
    auto_continue: bool
    target_video_limit: int | None
    failure_threshold_percent: int | None
    dispatched_count: int
    sync_run_id: str | None
    analysis_run_id: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class CreatorOverviewResponse(BaseModel):
    creator: CreatorResponse
    progress: dict[str, int]
    latest_sync: CreatorSyncRunResponse | None
    latest_profile: CreatorAnalysisResponse | None
    latest_skill: CreatorSkillSummary | None
    latest_research: CreatorResearchRunResponse | None
    recommended_action: str


class CreatorDashboardResponse(BaseModel):
    creator_count: int
    video_count: int
    transcript_count: int
    insight_count: int
    skill_count: int


class DouyinSessionStatus(BaseModel):
    status: str
    message: str
    last_verified_at: datetime | None = None
    qr_available: bool = False
    qr_updated_at: datetime | None = None
