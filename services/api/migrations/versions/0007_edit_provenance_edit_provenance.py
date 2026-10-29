"""edit_provenance"""

import sqlalchemy as sa
from alembic import op

revision = "0007_edit_provenance"
down_revision = "0006_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.add_column(
        "edit_overlays",
        sa.Column("updated_by", sa.Text(), server_default="legacy-unknown", nullable=False),
    )
    op.add_column(
        "edit_overlays",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column("reconciliation_conflicts", sa.Column("resolved_by", sa.Text(), nullable=True))
    op.add_column(
        "reconciliation_conflicts",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.drop_column("reconciliation_conflicts", "resolved_at")
    op.drop_column("reconciliation_conflicts", "resolved_by")
    op.drop_column("edit_overlays", "updated_at")
    op.drop_column("edit_overlays", "updated_by")
