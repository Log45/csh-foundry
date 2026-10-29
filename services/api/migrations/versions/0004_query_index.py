"""Measured, fixed-width status equality lookup; no per-property blanket indexing."""

import sqlalchemy as sa
from alembic import op

revision = "0004_query_index"
down_revision = "0003_snapshot_locks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Administrative CLI operation, never a request-handler index build. Fail/rollback
    # explicitly on a busy or oversized database; durable/concurrent jobs remain deferred.
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_index(
        "ix_objects_status_lookup",
        "objects",
        [
            "tenant_id",
            sa.text("md5(ontology_id)"),
            sa.text("md5(object_type_id)"),
            sa.text("md5(properties ->> 'operationalStatus')"),
        ],
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.drop_index("ix_objects_status_lookup", table_name="objects")
