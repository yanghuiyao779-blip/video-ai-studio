from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Job(Base):
    __tablename__ = "jobs"

    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_url: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(20), default="url")
    source_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform: Mapped[str | None] = mapped_column(String(40), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(80), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    asr_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    summary_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    summary_language: Mapped[str] = mapped_column(String(40), default="Chinese")
    summary_preset: Mapped[str] = mapped_column(String(60), default="standard")
    summary_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Creator(Base):
    __tablename__ = "creators"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    platform: Mapped[str] = mapped_column(String(40), index=True)
    profile_url: Mapped[str] = mapped_column(Text, unique=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    sec_user_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    platform_uid: Mapped[str | None] = mapped_column(String(160), nullable=True)
    resolution_method: Mapped[str | None] = mapped_column(String(80), nullable=True)
    platform_creator_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="ready", index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CreatorSyncRun(Base):
    __tablename__ = "creator_sync_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CreatorVideo(Base):
    __tablename__ = "creator_videos"
    __table_args__ = (UniqueConstraint("platform", "platform_video_id", name="uq_creator_video_platform_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(40), index=True)
    platform_video_id: Mapped[str] = mapped_column(String(160), index=True)
    video_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    # A video is claimed by at most one bounded research run.  This is what
    # lets retry/auto-advance accounting distinguish a current run from old
    # creator history.
    research_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("creator_research_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ingest_status: Mapped[str] = mapped_column(String(40), default="discovered", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class VideoInsight(Base):
    __tablename__ = "video_insights"
    __table_args__ = (UniqueConstraint("creator_video_id", "transcript_hash", "extractor_version", name="uq_video_insight_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    creator_video_id: Mapped[str] = mapped_column(ForeignKey("creator_videos.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    transcript_hash: Mapped[str] = mapped_column(String(64), index=True)
    extractor_version: Mapped[str] = mapped_column(String(80), default="v1")
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    insight_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CreatorAnalysisRun(Base):
    __tablename__ = "creator_analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    prompt_version: Mapped[str] = mapped_column(String(80), default="v1")
    input_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    profile_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CreatorSkillVersion(Base):
    __tablename__ = "creator_skill_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"), index=True)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("creator_analysis_runs.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="ready")
    skill_markdown: Mapped[str] = mapped_column(Text)
    artifact_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CreatorResearchRun(Base):
    """A user-visible, bounded orchestration run for creator research.

    The individual sync, media and LLM jobs remain independently auditable;
    this entity only records the high-level journey and its user controls.
    """
    __tablename__ = "creator_research_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    creator_id: Mapped[str] = mapped_column(ForeignKey("creators.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    batch_size: Mapped[int] = mapped_column(Integer, default=3)
    auto_continue: Mapped[bool] = mapped_column(Boolean, default=False)
    # None means no upper limit.  Existing runs deliberately retain this
    # legacy-safe behaviour after the migration.
    target_video_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_threshold_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dispatched_count: Mapped[int] = mapped_column(Integer, default=0)
    sync_run_id: Mapped[str | None] = mapped_column(ForeignKey("creator_sync_runs.id", ondelete="SET NULL"), nullable=True)
    analysis_run_id: Mapped[str | None] = mapped_column(ForeignKey("creator_analysis_runs.id", ondelete="SET NULL"), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

# Register the independent assistant metadata without changing media models.
from app.db import assistant as _assistant_models  # noqa: E402,F401
