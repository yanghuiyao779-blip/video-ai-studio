"""creator research orchestration runs

Revision ID: 0007_creator_research_runs
Revises: 0006_creator_identity
"""
from alembic import op
import sqlalchemy as sa


revision = "0007_creator_research_runs"
down_revision = "0006_creator_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "creator_research_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("creator_id", sa.String(36), sa.ForeignKey("creators.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="queued"),
        sa.Column("batch_size", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("auto_continue", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sync_run_id", sa.String(36), sa.ForeignKey("creator_sync_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("analysis_run_id", sa.String(36), sa.ForeignKey("creator_analysis_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_creator_research_runs_creator_id", "creator_research_runs", ["creator_id"])
    op.create_index("ix_creator_research_runs_status", "creator_research_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_creator_research_runs_status", table_name="creator_research_runs")
    op.drop_index("ix_creator_research_runs_creator_id", table_name="creator_research_runs")
    op.drop_table("creator_research_runs")
