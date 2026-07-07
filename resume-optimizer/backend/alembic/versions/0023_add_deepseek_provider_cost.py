"""add a deepseek provider_costs fallback row

resolve_cost() prefers LiteLLM's native per-call cost and only reads provider_costs
when LiteLLM can't price a call. deepseek/deepseek-v4-pro (the optimizer's
strategist, and the priciest model) has a custom model name LiteLLM may not map,
so without a deepseek fallback row those calls record cost_source="zero" ($0).

This inserts a deepseek row ONLY if none exists — it never overwrites rates an
operator has set for existing providers.

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-05
"""

import uuid as _uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing = conn.execute(
        sa.text("SELECT COUNT(*) FROM provider_costs WHERE provider = 'deepseek'")
    ).scalar()
    if existing and existing > 0:
        return

    provider_costs = sa.table(
        "provider_costs",
        sa.column("id", sa.Uuid()),
        sa.column("provider", sa.String()),
        sa.column("input_cost_per_1m_tokens", sa.Float()),
        sa.column("output_cost_per_1m_tokens", sa.Float()),
        sa.column("active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        provider_costs,
        [
            {
                "id": _uuid.uuid4(),
                "provider": "deepseek",
                "input_cost_per_1m_tokens": 0.28,   # USD per 1M tokens (fallback estimate)
                "output_cost_per_1m_tokens": 1.10,
                "active": True,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM provider_costs WHERE provider = 'deepseek'")
