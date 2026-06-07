"""Initial schema — creates all 5 tables.

Revision ID: 0001
Revises:
Create Date: 2026-06-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── plan_limits (no FK deps) ──────────────────────────────────────────────
    op.create_table(
        "plan_limits",
        sa.Column("plan", sa.String(50), primary_key=True),
        sa.Column("daily_uploads", sa.Integer(), nullable=False),
        sa.Column("max_stored_resumes", sa.Integer(), nullable=False),
        sa.Column("job_scraping_enabled", sa.Boolean(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
    )

    # ── users (no FK deps) ────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column(
            "plan",
            sa.Enum("free", "pro", "enterprise", name="plantype"),
            nullable=False,
        ),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── pipeline_jobs (FK → users) ────────────────────────────────────────────
    op.create_table(
        "pipeline_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "done", "error", name="jobstatus"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("resume_text", sa.Text(), nullable=False),
        sa.Column("jd_text", sa.Text(), nullable=True),
        sa.Column("scores_json", sa.JSON(), nullable=True),
        sa.Column("download_path", sa.String(1000), nullable=True),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_pipeline_jobs_user_id", "pipeline_jobs", ["user_id"])
    op.create_index("ix_pipeline_jobs_status", "pipeline_jobs", ["status"])

    # ── resumes (FK → users) ──────────────────────────────────────────────────
    op.create_table(
        "resumes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=True),
        sa.Column("jd_text", sa.Text(), nullable=True),
        sa.Column("final_score", sa.Float(), nullable=True),
        sa.Column("scores_json", sa.JSON(), nullable=True),
        sa.Column("iterations", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_resumes_user_id", "resumes", ["user_id"])

    # ── pipeline_events (FK → pipeline_jobs) ──────────────────────────────────
    op.create_table(
        "pipeline_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("pipeline_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_pipeline_events_job_id", "pipeline_events", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_events_job_id", table_name="pipeline_events")
    op.drop_table("pipeline_events")

    op.drop_index("ix_resumes_user_id", table_name="resumes")
    op.drop_table("resumes")

    op.drop_index("ix_pipeline_jobs_status", table_name="pipeline_jobs")
    op.drop_index("ix_pipeline_jobs_user_id", table_name="pipeline_jobs")
    op.drop_table("pipeline_jobs")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    op.drop_table("plan_limits")

    # Drop named enum types (no-op on SQLite, required on PostgreSQL)
    sa.Enum(name="jobstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="plantype").drop(op.get_bind(), checkfirst=True)
