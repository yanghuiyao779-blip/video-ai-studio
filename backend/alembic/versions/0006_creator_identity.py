"""stable douyin creator identity

Revision ID: 0006_creator_identity
Revises: 0005_creator_rag
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_creator_identity"
down_revision = "0005_creator_rag"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("creators", sa.Column("source_url", sa.Text(), nullable=True))
    op.add_column("creators", sa.Column("canonical_url", sa.Text(), nullable=True))
    op.add_column("creators", sa.Column("sec_user_id", sa.String(256), nullable=True))
    op.add_column("creators", sa.Column("platform_uid", sa.String(160), nullable=True))
    op.add_column("creators", sa.Column("resolution_method", sa.String(80), nullable=True))
    op.create_unique_constraint("uq_creator_platform_sec_user", "creators", ["platform", "sec_user_id"])

def downgrade() -> None:
    op.drop_constraint("uq_creator_platform_sec_user", "creators", type_="unique")
    for column in ("resolution_method", "platform_uid", "sec_user_id", "canonical_url", "source_url"):
        op.drop_column("creators", column)
