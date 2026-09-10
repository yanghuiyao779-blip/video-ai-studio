"""product ux fields

Revision ID: 0002_product_ux_fields
Revises: 0001_initial
Create Date: 2026-09-09
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_product_ux_fields"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep this migration compatible with both PostgreSQL (production) and
    # SQLite (Windows/local development). SQLite can add a NOT NULL column
    # safely when a server default is supplied in the same statement.
    op.add_column(
        "jobs",
        sa.Column("summary_preset", sa.String(length=60), nullable=False, server_default="standard"),
    )
    op.add_column("jobs", sa.Column("summary_instruction", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("error_code", sa.String(length=80), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("error_code")
        batch_op.drop_column("summary_instruction")
        batch_op.drop_column("summary_preset")
