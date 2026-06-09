"""normalize provider names to lowercase and add CHECK constraint

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-06
"""
from alembic import op
from sqlalchemy import text

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    op.execute(text("UPDATE provider_costs SET provider = lower(provider)"))
    if dialect == "postgresql":
        op.execute(
            text(
                "ALTER TABLE provider_costs ADD CONSTRAINT chk_provider_lower "
                "CHECK (provider = lower(provider))"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute(
            text(
                "ALTER TABLE provider_costs DROP CONSTRAINT IF EXISTS chk_provider_lower"
            )
        )
