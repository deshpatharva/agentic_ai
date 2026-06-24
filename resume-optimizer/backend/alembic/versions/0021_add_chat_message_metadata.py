"""add meta JSON column to chat_messages

`metadata` is a reserved attribute name on SQLAlchemy's Declarative base, so the
column is named `meta` instead.

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("meta", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "meta")
