"""add cached_input_tokens to llm_call_log

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_call_log",
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("llm_call_log", "cached_input_tokens")
