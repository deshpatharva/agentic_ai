"""Add promo_codes and user_promo_redemptions tables.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "promo_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("type", sa.String(50), nullable=False),  # plan_upgrade, trial_extension, discount
        sa.Column("target_plan", sa.String(20), nullable=True),
        sa.Column("days_to_add", sa.Integer(), nullable=True),
        sa.Column("discount_percent", sa.Integer(), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("current_uses", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "user_promo_redemptions",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("promo_code_id", sa.Uuid(), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["promo_code_id"], ["promo_codes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "promo_code_id", name="uq_user_code"),
    )


def downgrade() -> None:
    op.drop_table("user_promo_redemptions")
    op.drop_table("promo_codes")
