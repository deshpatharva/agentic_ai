"""fix timezone-naive datetime columns

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_TZ_TABLES = {
    "users":                   ["created_at"],
    "resumes":                 ["created_at"],
    "pipeline_jobs":           ["created_at", "updated_at"],
    "user_promo_redemptions":  ["redeemed_at"],
    "provider_costs":          ["created_at", "updated_at"],
}


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    for table, cols in _TZ_TABLES.items():
        with op.batch_alter_table(table) as batch_op:
            for col in cols:
                if dialect == "postgresql":
                    batch_op.alter_column(
                        col,
                        type_=sa.DateTime(timezone=True),
                        existing_type=sa.DateTime(),
                        existing_nullable=False,
                        postgresql_using=f"{col} AT TIME ZONE 'UTC'",
                    )
                else:
                    batch_op.alter_column(
                        col,
                        type_=sa.DateTime(timezone=True),
                        existing_type=sa.DateTime(),
                        existing_nullable=False,
                    )


def downgrade() -> None:
    for table, cols in _TZ_TABLES.items():
        with op.batch_alter_table(table) as batch_op:
            for col in cols:
                batch_op.alter_column(
                    col,
                    type_=sa.DateTime(),
                    existing_type=sa.DateTime(timezone=True),
                    existing_nullable=False,
                )
