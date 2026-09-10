"""local uploads

Revision ID: 0003_local_uploads
Revises: 0002_product_ux_fields
Create Date: 2026-09-09
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_local_uploads"
down_revision = "0002_product_ux_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("source_type", sa.String(length=20), nullable=False, server_default="url"),
    )
    op.add_column("jobs", sa.Column("source_filename", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("source_path", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("source_path")
        batch_op.drop_column("source_filename")
        batch_op.drop_column("source_type")
