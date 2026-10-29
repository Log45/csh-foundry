"""Measured bytewise identity ordering for bounded query pages."""

import sqlalchemy as sa
from alembic import op

revision = "0005_query_order"
down_revision = "0004_query_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_index(
        "ix_objects_query_order",
        "objects",
        ["tenant_id", "ontology_id", "object_type_id", sa.text('object_id COLLATE "C"')],
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.drop_index("ix_objects_query_order", table_name="objects")
