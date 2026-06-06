"""migrate datetime columns to timezone-aware

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "trial_expires_at",
            type_=sa.DateTime(timezone=True),
            existing_type=sa.DateTime(),
            existing_nullable=True,
        )
    with op.batch_alter_table("promo_codes") as batch_op:
        for col in ("expires_at", "deactivated_at", "created_at"):
            try:
                batch_op.alter_column(
                    col,
                    type_=sa.DateTime(timezone=True),
                    existing_type=sa.DateTime(),
                    existing_nullable=(col != "created_at"),
                )
            except Exception:
                pass


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "trial_expires_at",
            type_=sa.DateTime(),
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=True,
        )
