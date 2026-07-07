"""add LLM call observability columns

Failure capture and finish-reason tracking for llm_call_log. Until now the
exception paths in llm.py never reached the ledger, so error rates were
unknowable in-product. Columns follow OTel GenAI naming where sensible
(error_type ~ error.type, finish_reason ~ gen_ai.response.finish_reasons).
Existing rows backfill to status='ok' via the server default — every
pre-0027 row was by definition a success.

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_call_log", sa.Column("status", sa.String(16), nullable=False, server_default="ok"))
    op.add_column("llm_call_log", sa.Column("error_type", sa.String(100), nullable=True))
    op.add_column("llm_call_log", sa.Column("error_code", sa.String(40), nullable=True))
    op.add_column("llm_call_log", sa.Column("attempt", sa.SmallInteger(), nullable=False, server_default="1"))
    op.add_column("llm_call_log", sa.Column("finish_reason", sa.String(40), nullable=True))
    op.create_index("ix_llm_call_status_created", "llm_call_log", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_call_status_created", table_name="llm_call_log")
    for col in ("finish_reason", "attempt", "error_code", "error_type", "status"):
        op.drop_column("llm_call_log", col)
