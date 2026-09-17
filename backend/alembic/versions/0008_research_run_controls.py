"""creator research runtime controls and video ownership

Revision ID: 0008_research_run_controls
Revises: 0007_creator_research_runs
"""
from alembic import op
import sqlalchemy as sa


revision = "0008_research_run_controls"
down_revision = "0007_creator_research_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("creator_research_runs", sa.Column("target_video_limit", sa.Integer(), nullable=True))
    op.add_column("creator_research_runs", sa.Column("failure_threshold_percent", sa.Integer(), nullable=True))
    op.add_column("creator_research_runs", sa.Column("dispatched_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("creator_videos", sa.Column("research_run_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_creator_videos_research_run_id", "creator_videos", "creator_research_runs",
        ["research_run_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_creator_videos_research_run_id", "creator_videos", ["research_run_id"])


def downgrade() -> None:
    op.drop_index("ix_creator_videos_research_run_id", table_name="creator_videos")
    op.drop_constraint("fk_creator_videos_research_run_id", "creator_videos", type_="foreignkey")
    op.drop_column("creator_videos", "research_run_id")
    op.drop_column("creator_research_runs", "dispatched_count")
    op.drop_column("creator_research_runs", "failure_threshold_percent")
    op.drop_column("creator_research_runs", "target_video_limit")
