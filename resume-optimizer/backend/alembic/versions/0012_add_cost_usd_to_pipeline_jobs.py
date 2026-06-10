"""add cost_usd to pipeline_jobs

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_jobs",
        sa.Column("cost_usd", sa.Float(), nullable=True, server_default="0.0"),
    )


def downgrade() -> None:
    op.drop_column("pipeline_jobs", "cost_usd")
