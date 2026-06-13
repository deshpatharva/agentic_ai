"""add llm_call_log

Revision ID: 0016_add_llm_call_log
Revises: 0015_add_chat_sessions
Create Date: 2026-06-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0016_add_llm_call_log"
down_revision = "0015_add_chat_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_call_log",
        sa.Column("id",            sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trace_id",      sa.String(36), nullable=True),
        sa.Column("user_id",       sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("job_id",        sa.Uuid(), sa.ForeignKey("pipeline_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("model",         sa.String(100), nullable=False),
        sa.Column("provider",      sa.String(50), nullable=False),
        sa.Column("call_kind",     sa.String(40), nullable=True),
        sa.Column("input_tokens",  sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd",      sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("cost_source",   sa.String(20), nullable=False, server_default="litellm"),
        sa.Column("latency_ms",    sa.Integer(), nullable=True),
        sa.Column("ttft_ms",       sa.Integer(), nullable=True),
        sa.Column("cache_hit",     sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at",    sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_llm_call_log_trace_id",    "llm_call_log", ["trace_id"])
    op.create_index("ix_llm_call_log_user_id",     "llm_call_log", ["user_id"])
    op.create_index("ix_llm_call_log_job_id",      "llm_call_log", ["job_id"])
    op.create_index("ix_llm_call_log_model",       "llm_call_log", ["model"])
    op.create_index("ix_llm_call_log_provider",    "llm_call_log", ["provider"])
    op.create_index("ix_llm_call_log_created_at",  "llm_call_log", ["created_at"])
    op.create_index("ix_llm_call_model_created",   "llm_call_log", ["model", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_call_model_created",  "llm_call_log")
    op.drop_index("ix_llm_call_log_created_at", "llm_call_log")
    op.drop_index("ix_llm_call_log_provider",   "llm_call_log")
    op.drop_index("ix_llm_call_log_model",      "llm_call_log")
    op.drop_index("ix_llm_call_log_job_id",     "llm_call_log")
    op.drop_index("ix_llm_call_log_user_id",    "llm_call_log")
    op.drop_index("ix_llm_call_log_trace_id",   "llm_call_log")
    op.drop_table("llm_call_log")
