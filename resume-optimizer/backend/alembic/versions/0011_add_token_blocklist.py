"""add token_blocklist table for JWT revocation

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "token_blocklist",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("jti", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jti", name="uq_token_blocklist_jti"),
    )
    op.create_index("ix_token_blocklist_jti", "token_blocklist", ["jti"])


def downgrade() -> None:
    op.drop_index("ix_token_blocklist_jti", "token_blocklist")
    op.drop_table("token_blocklist")
