"""Chat, projects, scoped media ownership and independent knowledge indexes.

Frozen schema: this migration deliberately does not import application models.
Revision ID: 0009_assistant_workspace
Revises: 0008_research_run_controls
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_assistant_workspace"
down_revision = "0008_research_run_controls"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("owner_id", sa.String(36), nullable=True))
    op.create_foreign_key("fk_jobs_owner_id", "jobs", "users", ["owner_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_jobs_owner_id", "jobs", ["owner_id"])
    op.create_table('assistant_workspaces',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('instructions', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_assistant_workspaces_owner_id'), 'assistant_workspaces', ['owner_id'], unique=False)
    op.create_table('assistant_workspace_members',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('workspace_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['assistant_workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workspace_id', 'user_id', name='uq_workspace_member')
    )
    op.create_index(op.f('ix_assistant_workspace_members_user_id'), 'assistant_workspace_members', ['user_id'], unique=False)
    op.create_index(op.f('ix_assistant_workspace_members_workspace_id'), 'assistant_workspace_members', ['workspace_id'], unique=False)
    op.create_table('assistant_workspace_resources',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('workspace_id', sa.String(length=36), nullable=False),
    sa.Column('job_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['assistant_workspaces.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workspace_id', 'job_id', name='uq_workspace_job')
    )
    op.create_index(op.f('ix_assistant_workspace_resources_job_id'), 'assistant_workspace_resources', ['job_id'], unique=False)
    op.create_index(op.f('ix_assistant_workspace_resources_workspace_id'), 'assistant_workspace_resources', ['workspace_id'], unique=False)
    op.create_table('conversations',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('workspace_id', sa.String(length=36), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('pinned', sa.Boolean(), nullable=False),
    sa.Column('archived', sa.Boolean(), nullable=False),
    sa.Column('tags', sa.JSON(), nullable=False),
    sa.Column('active_run_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['assistant_workspaces.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_conversations_owner_id'), 'conversations', ['owner_id'], unique=False)
    op.create_index(op.f('ix_conversations_updated_at'), 'conversations', ['updated_at'], unique=False)
    op.create_index(op.f('ix_conversations_workspace_id'), 'conversations', ['workspace_id'], unique=False)
    op.create_table('video_knowledge_chunks',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('job_id', sa.String(length=36), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('start_seconds', sa.Float(), nullable=False),
    sa.Column('end_seconds', sa.Float(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('embedding', sa.Text(), nullable=True),
    sa.Column('embedding_model', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_video_knowledge_chunks_job_id'), 'video_knowledge_chunks', ['job_id'], unique=False)
    op.create_table('video_knowledge_indexes',
    sa.Column('job_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('transcript_hash', sa.String(length=64), nullable=False),
    sa.Column('embedding_model', sa.String(length=200), nullable=False),
    sa.Column('chunk_count', sa.Integer(), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('job_id')
    )
    op.create_table('chat_messages',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('conversation_id', sa.String(length=36), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('meta', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_chat_messages_conversation_id'), 'chat_messages', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_chat_messages_created_at'), 'chat_messages', ['created_at'], unique=False)
    op.create_table('conversation_resources',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('conversation_id', sa.String(length=36), nullable=False),
    sa.Column('job_id', sa.String(length=36), nullable=True),
    sa.Column('creator_id', sa.String(length=36), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('(job_id IS NOT NULL AND creator_id IS NULL) OR (job_id IS NULL AND creator_id IS NOT NULL)', name='ck_resource_exactly_one'),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['creator_id'], ['creators.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('conversation_id', 'creator_id', name='uq_conversation_creator'),
    sa.UniqueConstraint('conversation_id', 'job_id', name='uq_conversation_job')
    )
    op.create_index(op.f('ix_conversation_resources_conversation_id'), 'conversation_resources', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_conversation_resources_creator_id'), 'conversation_resources', ['creator_id'], unique=False)
    op.create_index(op.f('ix_conversation_resources_job_id'), 'conversation_resources', ['job_id'], unique=False)
    op.create_table('conversation_shares',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('conversation_id', sa.String(length=36), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('snapshot', sa.JSON(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_conversation_shares_conversation_id'), 'conversation_shares', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_conversation_shares_token_hash'), 'conversation_shares', ['token_hash'], unique=True)
    op.create_table('chat_runs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('conversation_id', sa.String(length=36), nullable=False),
    sa.Column('requested_by', sa.String(length=36), nullable=False),
    sa.Column('assistant_message_id', sa.String(length=36), nullable=False),
    sa.Column('user_message_id', sa.String(length=36), nullable=False),
    sa.Column('client_request_id', sa.String(length=80), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('stage', sa.String(length=80), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('trace', sa.JSON(), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('cancel_requested', sa.Boolean(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('lease_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['assistant_message_id'], ['chat_messages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_message_id'], ['chat_messages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('conversation_id', 'client_request_id', name='uq_chat_request')
    )
    op.create_index(op.f('ix_chat_runs_conversation_id'), 'chat_runs', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_chat_runs_status'), 'chat_runs', ['status'], unique=False)
    op.create_index(op.f('ix_chat_runs_updated_at'), 'chat_runs', ['updated_at'], unique=False)
    op.create_table('assistant_artifacts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('conversation_id', sa.String(length=36), nullable=False),
    sa.Column('run_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('structured', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['chat_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'kind', name='uq_run_artifact')
    )
    op.create_index(op.f('ix_assistant_artifacts_conversation_id'), 'assistant_artifacts', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_assistant_artifacts_run_id'), 'assistant_artifacts', ['run_id'], unique=False)

    # 0005 already enables pgvector. A portable TEXT vector encoding is used in
    # SQLite; PostgreSQL accelerates it with an expression HNSW cosine index.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE INDEX ix_video_chunks_vector ON video_knowledge_chunks USING hnsw ((embedding::vector(1536)) vector_cosine_ops) WHERE embedding IS NOT NULL")
    # Legacy jobs are adopted by ADMIN_USERNAME in bootstrap_database once the
    # configured deployment admin exists, never guessed by migration row order.


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_video_chunks_vector")
    op.drop_table('assistant_artifacts')
    op.drop_table('chat_runs')
    op.drop_table('conversation_shares')
    op.drop_table('conversation_resources')
    op.drop_table('chat_messages')
    op.drop_table('video_knowledge_indexes')
    op.drop_table('video_knowledge_chunks')
    op.drop_table('conversations')
    op.drop_table('assistant_workspace_resources')
    op.drop_table('assistant_workspace_members')
    op.drop_table('assistant_workspaces')
    op.drop_index("ix_jobs_owner_id", table_name="jobs")
    op.drop_constraint("fk_jobs_owner_id", "jobs", type_="foreignkey")
    op.drop_column("jobs", "owner_id")
