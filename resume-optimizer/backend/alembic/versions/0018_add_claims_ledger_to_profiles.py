"""add claims_ledger_json to profiles

Revision ID: 0018_add_claims_ledger
Revises: 0017_session_and_profile
Create Date: 2026-06-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0018_add_claims_ledger"
down_revision = "0017_session_and_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("claims_ledger_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("profiles", "claims_ledger_json")
