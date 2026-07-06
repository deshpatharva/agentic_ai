"""correct legacy provider_costs magnitudes

Databases seeded before the magnitude fix (commit e372be6) hold per-1K-scale
rates for anthropic/google/groq — roughly 1000x too low — so any call priced via
the ProviderCost fallback under-reports cost. The fresh-install seed and the
deepseek migration (0023) did not touch these existing rows.

This corrects ONLY rows whose active rate still exactly equals the old seeded
values, so an operator's intentionally-customized rate is never overwritten.

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-06
"""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

# (provider, old_input, old_output, new_input, new_output) — USD per 1M tokens.
# The new values match utils.cost.DEFAULT_PROVIDER_RATES (the live seed/admin
# source of truth); kept literal here so the migration stays frozen in time.
_LEGACY_CORRECTIONS = [
    ("anthropic", 0.003,  0.009,  3.0,  15.0),
    ("google",    0.0005, 0.0015, 0.10, 0.40),
    ("groq",      0.0001, 0.0001, 0.05, 0.08),
]

_UPDATE = sa.text(
    "UPDATE provider_costs SET input_cost_per_1m_tokens = :new_in, "
    "output_cost_per_1m_tokens = :new_out, updated_at = :now "
    "WHERE provider = :provider AND active "
    "AND input_cost_per_1m_tokens = :old_in AND output_cost_per_1m_tokens = :old_out"
)


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    for provider, old_in, old_out, new_in, new_out in _LEGACY_CORRECTIONS:
        conn.execute(_UPDATE, {
            "provider": provider, "old_in": old_in, "old_out": old_out,
            "new_in": new_in, "new_out": new_out, "now": now,
        })


def downgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    # Reverse only rows we would have corrected (still at the corrected values).
    for provider, old_in, old_out, new_in, new_out in _LEGACY_CORRECTIONS:
        conn.execute(_UPDATE, {
            "provider": provider, "old_in": new_in, "old_out": new_out,
            "new_in": old_in, "new_out": old_out, "now": now,
        })
