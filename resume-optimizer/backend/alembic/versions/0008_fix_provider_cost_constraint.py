"""replace uq_provider_active with partial unique index

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-06
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        op.drop_constraint("uq_provider_active", "provider_costs", type_="unique")
        op.execute(
            "CREATE UNIQUE INDEX uix_provider_active_true "
            "ON provider_costs (provider) WHERE active = true"
        )
    # SQLite: UniqueConstraint was defined in the model only; no ALTER needed.
    # The constraint does not exist in the schema when created via SQLite
    # (batch migration creates fresh tables without the named constraint).


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS uix_provider_active_true")
        op.create_unique_constraint(
            "uq_provider_active", "provider_costs", ["provider", "active"]
        )
