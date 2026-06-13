"""add profiles table, profile_id on resumes, jd_scrape_cache

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _table_exists(conn, name: str) -> bool:
    return conn.dialect.has_table(conn, name)


def _column_exists(conn, table: str, column: str) -> bool:
    # Dialect-portable (SQLite has no information_schema)
    cols = sa.inspect(conn).get_columns(table)
    return any(c["name"] == column for c in cols)


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "profiles"):
        op.create_table(
            "profiles",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("label", sa.String(100), nullable=True),
            sa.Column("label_confirmed", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("raw_text", sa.Text(), nullable=True),
            sa.Column("sections", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_profiles_user_id", "profiles", ["user_id"])

    if not _column_exists(conn, "resumes", "profile_id"):
        if conn.dialect.name == "sqlite":
            # SQLite can't ALTER in a FK constraint — batch mode recreates the table.
            with op.batch_alter_table("resumes") as batch_op:
                batch_op.add_column(sa.Column("profile_id", sa.Uuid(), nullable=True))
                batch_op.create_foreign_key(
                    "fk_resumes_profile_id", "profiles",
                    ["profile_id"], ["id"], ondelete="SET NULL",
                )
        else:
            op.add_column(
                "resumes",
                sa.Column("profile_id", sa.Uuid(), sa.ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True),
            )
        op.create_index("ix_resumes_profile_id", "resumes", ["profile_id"])

    if not _table_exists(conn, "jd_scrape_cache"):
        op.create_table(
            "jd_scrape_cache",
            sa.Column("url_hash", sa.String(64), primary_key=True),
            sa.Column("jd_text", sa.Text(), nullable=False),
            sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )


def downgrade() -> None:
    op.drop_table("jd_scrape_cache")
    op.drop_index("ix_resumes_profile_id", table_name="resumes")
    op.drop_column("resumes", "profile_id")
    op.drop_index("ix_profiles_user_id", table_name="profiles")
    op.drop_table("profiles")
