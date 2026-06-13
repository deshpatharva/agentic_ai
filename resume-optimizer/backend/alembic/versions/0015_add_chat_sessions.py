"""add chat_sessions and chat_messages

Revision ID: 0015_add_chat_sessions
Revises: 0014_add_tokens_to_pipeline_jobs
Create Date: 2026-06-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0015_add_chat_sessions"
down_revision = "0014_add_tokens_to_pipeline_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("pipeline_jobs.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Uuid(),
                  sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session_id", "chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_user_id", "chat_sessions")
    op.drop_table("chat_sessions")
