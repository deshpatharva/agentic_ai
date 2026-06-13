"""add input/output token counts to pipeline_jobs

Per-run token counts previously existed only in the 24h-TTL `done` SSE event;
persisting them makes the admin Pipeline Runs view durable for cost analysis.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def _column_exists(conn, table: str, column: str) -> bool:
    cols = sa.inspect(conn).get_columns(table)
    return any(c["name"] == column for c in cols)


def upgrade() -> None:
    conn = op.get_bind()
    if not _column_exists(conn, "pipeline_jobs", "input_tokens"):
        op.add_column("pipeline_jobs", sa.Column("input_tokens", sa.Integer(), nullable=True))
    if not _column_exists(conn, "pipeline_jobs", "output_tokens"):
        op.add_column("pipeline_jobs", sa.Column("output_tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("pipeline_jobs", "output_tokens")
    op.drop_column("pipeline_jobs", "input_tokens")
