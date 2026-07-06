"""add pipeline_jobs.quota_refunded

The run-quota slot reserved at submission is refunded on failure. Both the
failing pipeline task and the stuck-job reaper can reach a job, so the refund
must be idempotent per job — this flag is flipped exactly once (atomic
UPDATE ... WHERE quota_refunded = false) and gates the counter decrement.

Existing rows are backfilled to true: any run that predates this column has
already resolved (its counter was reconciled under the old scheme), so it must
not be eligible for a refund.

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_jobs",
        sa.Column("quota_refunded", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Pre-existing jobs already had their quota settled — don't let the reaper
    # refund them retroactively.
    op.execute("UPDATE pipeline_jobs SET quota_refunded = true")


def downgrade() -> None:
    op.drop_column("pipeline_jobs", "quota_refunded")
