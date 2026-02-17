"""Add spheres table, step_bank table, new columns to focuses and daily_sessions.

Revision ID: 001
Revises: (initial — no prior migration files)
Create Date: 2026-02-15
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    """Check if column exists in table (PostgreSQL)."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    )
    return result.fetchone() is not None


def _table_exists(table: str) -> bool:
    """Check if table exists (PostgreSQL)."""
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
    # ── 1. Create spheres table ──────────────────────────────────────────────
    if not _table_exists("spheres"):
        op.create_table(
            "spheres",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("is_custom", sa.Boolean, server_default="false"),
            sa.Column("satisfaction", sa.Integer, nullable=True),
            sa.Column("importance", sa.Integer, nullable=True),
            sa.Column("pain_text", sa.Text, nullable=True),
            sa.Column("is_priority", sa.Boolean, server_default="false"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "name", name="uq_user_sphere"),
        )

    # ── 2. Create step_bank table ────────────────────────────────────────────
    if not _table_exists("step_bank"):
        op.create_table(
            "step_bank",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("focus_id", sa.Integer, sa.ForeignKey("focuses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("week_number", sa.Integer, nullable=True),
            sa.Column("step_text", sa.Text, nullable=False),
            sa.Column("plan_b_text", sa.Text, nullable=True),
            sa.Column("is_used", sa.Boolean, server_default="false"),
            sa.Column("order", sa.Integer, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    # ── 3. Add new columns to focuses ────────────────────────────────────────
    new_focus_columns = [
        ("sphere_id", sa.Integer(), None),
        ("meaning", sa.Text(), None),
        ("metric", sa.Text(), None),
        ("cost", sa.Text(), None),
        ("llm_score", sa.String(20), None),
        ("llm_reframe", sa.Text(), None),
        ("is_active", sa.Boolean(), "true"),
        ("week_number", sa.Integer(), None),
    ]
    for col_name, col_type, default in new_focus_columns:
        if not _column_exists("focuses", col_name):
            kw = {}
            if default is not None:
                kw["server_default"] = default
            op.add_column("focuses", sa.Column(col_name, col_type, nullable=True, **kw))

    # Add FK constraint for sphere_id if column was just created
    if _column_exists("focuses", "sphere_id"):
        try:
            op.create_foreign_key(
                "fk_focuses_sphere_id", "focuses", "spheres",
                ["sphere_id"], ["id"], ondelete="SET NULL",
            )
        except Exception:
            pass  # constraint may already exist

    # Add updated_at to focuses if missing
    if not _column_exists("focuses", "updated_at"):
        op.add_column(
            "focuses",
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    # ── 4. Add new columns to daily_sessions ─────────────────────────────────
    if not _column_exists("daily_sessions", "household_tasks"):
        op.add_column("daily_sessions", sa.Column("household_tasks", sa.JSON, nullable=True))

    if not _column_exists("daily_sessions", "step_bank_id"):
        op.add_column("daily_sessions", sa.Column("step_bank_id", sa.Integer, nullable=True))
        try:
            op.create_foreign_key(
                "fk_daily_sessions_step_bank_id", "daily_sessions", "step_bank",
                ["step_bank_id"], ["id"], ondelete="SET NULL",
            )
        except Exception:
            pass

    # ── 5. Remove old spheres column from users if it exists ─────────────────
    if _column_exists("users", "spheres"):
        op.drop_column("users", "spheres")


def downgrade() -> None:
    # Add back old spheres column to users
    op.add_column("users", sa.Column("spheres", sa.Text, nullable=True))

    # Remove new columns from daily_sessions
    op.drop_column("daily_sessions", "step_bank_id")
    op.drop_column("daily_sessions", "household_tasks")

    # Remove new columns from focuses
    for col in ["sphere_id", "meaning", "metric", "cost", "llm_score",
                "llm_reframe", "is_active", "week_number", "updated_at"]:
        op.drop_column("focuses", col)

    # Drop new tables
    op.drop_table("step_bank")
    op.drop_table("spheres")
