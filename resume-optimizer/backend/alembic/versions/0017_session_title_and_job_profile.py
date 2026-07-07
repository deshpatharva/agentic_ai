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
    conn = op.get_bind()

    op.add_column("chat_sessions", sa.Column("title", sa.String(120), nullable=True))

    # SQLite can't ALTER in an FK constraint — batch mode recreates the table.
    if conn.dialect.name == "sqlite":
        with op.batch_alter_table("pipeline_jobs") as batch_op:
            batch_op.add_column(sa.Column("profile_id", sa.Uuid(), nullable=True))
            batch_op.create_foreign_key(
                "fk_pipeline_jobs_profile_id", "profiles",
                ["profile_id"], ["id"], ondelete="SET NULL",
            )
    else:
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
