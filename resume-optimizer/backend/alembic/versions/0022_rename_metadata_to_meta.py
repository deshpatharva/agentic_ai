"""rename chat_messages.metadata → meta (idempotent)

If migration 0021 ran before the rename fix, the DB has a 'metadata' column
that needs to be renamed to 'meta'. If 0021 already created 'meta' (new code),
this migration is a no-op.

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-24
"""

from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    # Dialect-portable (SQLite has no information_schema) — same pattern as 0013.
    conn = op.get_bind()
    cols = sa.inspect(conn).get_columns(table)
    return any(c["name"] == column for c in cols)


def upgrade() -> None:
    has_metadata = _column_exists("chat_messages", "metadata")
    has_meta = _column_exists("chat_messages", "meta")

    if has_metadata and not has_meta:
        # batch_alter_table so the rename works on SQLite (no native ALTER RENAME
        # COLUMN through Alembic's default path); on Postgres it's a plain ALTER.
        with op.batch_alter_table("chat_messages") as batch_op:
            batch_op.alter_column("metadata", new_column_name="meta")
    elif not has_metadata and not has_meta:
        op.add_column(
            "chat_messages",
            sa.Column("meta", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    pass
