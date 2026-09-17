"""creator vector RAG

Revision ID: 0005_creator_rag
Revises: 0004_creator_intelligence
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_creator_rag"
down_revision = "0004_creator_intelligence"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("""CREATE TABLE creator_corpus_chunks (
      id uuid PRIMARY KEY, creator_id varchar(36) NOT NULL REFERENCES creators(id) ON DELETE CASCADE,
      creator_video_id varchar(36) NOT NULL REFERENCES creator_videos(id) ON DELETE CASCADE,
      job_id varchar(36) NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
      start_seconds double precision NOT NULL, end_seconds double precision NOT NULL,
      content text NOT NULL, embedding vector(1536) NOT NULL, created_at timestamptz NOT NULL)""")
    op.execute("CREATE INDEX ix_creator_corpus_creator ON creator_corpus_chunks (creator_id)")
    op.execute("CREATE INDEX ix_creator_corpus_embedding ON creator_corpus_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)")

def downgrade() -> None:
    op.drop_table("creator_corpus_chunks")
