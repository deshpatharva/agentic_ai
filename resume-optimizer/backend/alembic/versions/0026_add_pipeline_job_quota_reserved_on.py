"""add pipeline_jobs.quota_reserved_on

The daily-run reservation increments the counter row for the date the
reservation is made (date.today() at claim time), but the refund was attributed
to created_at — a different calendar day for prepare-Monday/run-Tuesday flows
and error-job retries, so the refund silently no-oped. Stamping the reservation
date on the job lets the refund target the exact row the reservation took.

NULL means "reserved before this column existed" — refunds for those rows fall
back to created_at, matching the old behavior.

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_jobs",
        sa.Column("quota_reserved_on", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pipeline_jobs", "quota_reserved_on")
