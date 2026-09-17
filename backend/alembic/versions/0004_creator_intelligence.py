"""creator intelligence MVP

Revision ID: 0004_creator_intelligence
Revises: 0003_local_uploads
Create Date: 2026-09-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_creator_intelligence"
down_revision = "0003_local_uploads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("creators", sa.Column("id", sa.String(36), primary_key=True), sa.Column("platform", sa.String(40), nullable=False), sa.Column("profile_url", sa.Text(), nullable=False, unique=True), sa.Column("platform_creator_id", sa.String(160)), sa.Column("name", sa.Text()), sa.Column("avatar_url", sa.Text()), sa.Column("status", sa.String(40), nullable=False), sa.Column("last_synced_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_creators_platform", "creators", ["platform"]); op.create_index("ix_creators_platform_creator_id", "creators", ["platform_creator_id"]); op.create_index("ix_creators_status", "creators", ["status"])
    op.create_table("creator_sync_runs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("creator_id", sa.String(36), sa.ForeignKey("creators.id", ondelete="CASCADE"), nullable=False), sa.Column("status", sa.String(40), nullable=False), sa.Column("cursor", sa.Text()), sa.Column("discovered_count", sa.Integer(), nullable=False), sa.Column("created_count", sa.Integer(), nullable=False), sa.Column("error_message", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_creator_sync_runs_creator_id", "creator_sync_runs", ["creator_id"]); op.create_index("ix_creator_sync_runs_status", "creator_sync_runs", ["status"])
    op.create_table("creator_videos", sa.Column("id", sa.String(36), primary_key=True), sa.Column("creator_id", sa.String(36), sa.ForeignKey("creators.id", ondelete="CASCADE"), nullable=False), sa.Column("platform", sa.String(40), nullable=False), sa.Column("platform_video_id", sa.String(160), nullable=False), sa.Column("video_url", sa.Text(), nullable=False), sa.Column("title", sa.Text()), sa.Column("published_at", sa.DateTime(timezone=True)), sa.Column("duration", sa.Integer()), sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="SET NULL")), sa.Column("ingest_status", sa.String(40), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("platform", "platform_video_id", name="uq_creator_video_platform_id"))
    for col in ("creator_id", "platform", "platform_video_id", "job_id", "ingest_status"): op.create_index(f"ix_creator_videos_{col}", "creator_videos", [col])
    op.create_table("video_insights", sa.Column("id", sa.String(36), primary_key=True), sa.Column("creator_video_id", sa.String(36), sa.ForeignKey("creator_videos.id", ondelete="CASCADE"), nullable=False), sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False), sa.Column("transcript_hash", sa.String(64), nullable=False), sa.Column("extractor_version", sa.String(80), nullable=False), sa.Column("status", sa.String(40), nullable=False), sa.Column("insight_json", sa.Text()), sa.Column("error_message", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("creator_video_id", "transcript_hash", "extractor_version", name="uq_video_insight_version"))
    for col in ("creator_video_id", "job_id", "transcript_hash", "status"): op.create_index(f"ix_video_insights_{col}", "video_insights", [col])
    op.create_table("creator_analysis_runs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("creator_id", sa.String(36), sa.ForeignKey("creators.id", ondelete="CASCADE"), nullable=False), sa.Column("status", sa.String(40), nullable=False), sa.Column("prompt_version", sa.String(80), nullable=False), sa.Column("input_snapshot_json", sa.Text(), nullable=False), sa.Column("profile_json", sa.Text()), sa.Column("error_message", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_creator_analysis_runs_creator_id", "creator_analysis_runs", ["creator_id"]); op.create_index("ix_creator_analysis_runs_status", "creator_analysis_runs", ["status"])
    op.create_table("creator_skill_versions", sa.Column("id", sa.String(36), primary_key=True), sa.Column("creator_id", sa.String(36), sa.ForeignKey("creators.id", ondelete="CASCADE"), nullable=False), sa.Column("analysis_run_id", sa.String(36), sa.ForeignKey("creator_analysis_runs.id", ondelete="CASCADE"), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("status", sa.String(40), nullable=False), sa.Column("skill_markdown", sa.Text(), nullable=False), sa.Column("artifact_dir", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_creator_skill_versions_creator_id", "creator_skill_versions", ["creator_id"]); op.create_index("ix_creator_skill_versions_analysis_run_id", "creator_skill_versions", ["analysis_run_id"])


def downgrade() -> None:
    for table in ("creator_skill_versions", "creator_analysis_runs", "video_insights", "creator_videos", "creator_sync_runs", "creators"):
        op.drop_table(table)
