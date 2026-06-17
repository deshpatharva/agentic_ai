"""add daily_edits to plan_limits and edits to daily_usage_counters

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def _column_exists(conn, table: str, column: str) -> bool:
    cols = sa.inspect(conn).get_columns(table)
    return any(c["name"] == column for c in cols)


def upgrade() -> None:
    conn = op.get_bind()

    if not _column_exists(conn, "plan_limits", "daily_edits"):
        op.add_column(
            "plan_limits",
            sa.Column("daily_edits", sa.Integer(), nullable=False, server_default="5"),
        )
        op.execute("UPDATE plan_limits SET daily_edits = 20 WHERE plan = 'pro'")
        op.execute("UPDATE plan_limits SET daily_edits = 999 WHERE plan = 'enterprise'")

    if not _column_exists(conn, "daily_usage_counters", "edits"):
        op.add_column(
            "daily_usage_counters",
            sa.Column("edits", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    op.drop_column("daily_usage_counters", "edits")
    op.drop_column("plan_limits", "daily_edits")
