"""add chat_sessions.title and pipeline_jobs.profile_id

Revision ID: 0017_session_title_and_job_profile
Revises: 0016_add_llm_call_log
Create Date: 2026-06-14
"""
import sqlalchemy as sa
from alembic import op

revision = "0017_session_and_profile"
down_revision = "0016_add_llm_call_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_sessions", sa.Column("title", sa.String(120), nullable=True))
    op.add_column(
        "pipeline_jobs",
        sa.Column(
            "profile_id",
            sa.Uuid(),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_pipeline_jobs_profile_id", "pipeline_jobs", ["profile_id"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_jobs_profile_id", "pipeline_jobs")
    op.drop_column("pipeline_jobs", "profile_id")
    op.drop_column("chat_sessions", "title")
