"""add daily_usage_counters table

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_usage_counters",
        sa.Column("id",      sa.Integer(),   primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Uuid(),       sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date",    sa.String(10),   nullable=False),
        sa.Column("runs",    sa.Integer(),    nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", "date", name="uq_user_date"),
    )
    op.create_index("ix_daily_usage_user_date", "daily_usage_counters", ["user_id", "date"])


def downgrade() -> None:
    op.drop_index("ix_daily_usage_user_date", table_name="daily_usage_counters")
    op.drop_table("daily_usage_counters")
