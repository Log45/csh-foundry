"""Encrypted browser state and shared admission budgets; no operational data rewrite."""

import sqlalchemy as sa
from alembic import op

revision = "0016_operations"
down_revision = "0015_sdk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        "browser_state",
        sa.Column("kind", sa.String(10), primary_key=True),
        sa.Column("key", sa.String(43), primary_key=True),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("kind IN ('login','session')", name="ck_browser_kind"),
        sa.CheckConstraint("revision > 0", name="ck_browser_revision"),
        sa.CheckConstraint("octet_length(ciphertext) <= 32768", name="ck_browser_size"),
    )
    op.create_index("ix_browser_state_expires_at", "browser_state", ["expires_at"])
    op.create_table(
        "request_budgets",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("window_minute", sa.BigInteger(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.CheckConstraint("count > 0", name="ck_budget_count"),
    )


def downgrade() -> None:
    # Session destruction forces reauthentication; do not reverse Phase 9 history migrations.
    op.drop_table("request_budgets")
    op.drop_table("browser_state")
