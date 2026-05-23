"""Add user contexts for week and month.

Revision ID: 002
Revises: 001
Create Date: 2026-05-23
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :table"
        ),
        {"table": table},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    if not _table_exists("user_contexts"):
        op.create_table(
            "user_contexts",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("period", sa.String(10), nullable=False),
            sa.Column("text", sa.Text, nullable=False, server_default=""),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "period", name="uq_user_context_period"),
        )


def downgrade() -> None:
    if _table_exists("user_contexts"):
        op.drop_table("user_contexts")
