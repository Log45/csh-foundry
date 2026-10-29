"""actions"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_actions"
down_revision = "0005_query_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        "action_executions",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.Text(), nullable=False),
        sa.Column("action_version", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status = 'COMMITTED'", name="ck_execution_status"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "schema_version"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
            ],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "ontology_id", "id"),
        sa.UniqueConstraint(
            "tenant_id", "ontology_id", "principal_id", "key_hash", name="uq_action_key"
        ),
    )
    op.create_index(
        "ix_action_history",
        "action_executions",
        ["tenant_id", "ontology_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "reconciliation_conflicts",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("object_type_id", sa.Text(), nullable=False),
        sa.Column("object_id", sa.Text(), nullable=False),
        sa.Column("property_id", sa.Text(), nullable=False),
        sa.Column("incoming", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("observed_revision", sa.BigInteger(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('OPEN','PRESERVED','ACCEPTED')", name="ck_reconciliation_status"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "schema_version"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
            ],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "ontology_id", "id"),
    )
    op.create_index(
        "ix_reconciliation_object",
        "reconciliation_conflicts",
        ["tenant_id", "ontology_id", "object_type_id", "object_id", "status"],
        unique=False,
    )
    op.create_table(
        "action_audit_events",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("object_type_id", sa.Text(), nullable=False),
        sa.Column("object_id", sa.Text(), nullable=False),
        sa.Column("operation", sa.String(length=30), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "execution_id"],
            [
                "action_executions.tenant_id",
                "action_executions.ontology_id",
                "action_executions.id",
            ],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "ontology_id", "id"),
    )
    op.create_index(
        "ix_action_audit_object",
        "action_audit_events",
        ["tenant_id", "ontology_id", "object_type_id", "object_id"],
        unique=False,
    )
    op.create_table(
        "edit_overlays",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("object_type_id", sa.Text(), nullable=False),
        sa.Column("object_id", sa.Text(), nullable=False),
        sa.Column("property_id", sa.Text(), nullable=False),
        sa.Column("owner", sa.String(length=20), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "owner IN ('source','pipeline','user','action')", name="ck_overlay_owner"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "execution_id"],
            [
                "action_executions.tenant_id",
                "action_executions.ontology_id",
                "action_executions.id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "schema_version"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
            ],
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "ontology_id", "object_type_id", "object_id", "property_id"
        ),
    )
    op.create_table(
        "outbox_events",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("destination", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("last_error", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("category = 'action.committed'", name="ck_event_category"),
        sa.CheckConstraint(
            "status IN ('PENDING','CLAIMED','DELIVERED','DEAD')", name="ck_event_status"
        ),
        sa.CheckConstraint("attempts >= 0 AND attempts <= 5", name="ck_event_attempts"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "execution_id"],
            [
                "action_executions.tenant_id",
                "action_executions.ontology_id",
                "action_executions.id",
            ],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "ontology_id", "id"),
        sa.UniqueConstraint(
            "tenant_id", "ontology_id", "execution_id", "category", name="uq_action_event"
        ),
    )
    op.create_index(
        "ix_outbox_pending", "outbox_events", ["status", "next_attempt_at"], unique=False
    )
    op.create_table(
        "webhook_attempts",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "event_id"],
            ["outbox_events.tenant_id", "outbox_events.ontology_id", "outbox_events.id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "ontology_id", "id"),
        sa.UniqueConstraint(
            "tenant_id", "ontology_id", "event_id", "attempt", name="uq_delivery_attempt"
        ),
    )
    op.execute("""
        CREATE FUNCTION protect_action_history() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'action history is append-only' USING ERRCODE = '23514';
        END $$
    """)
    for table in ("action_executions", "action_audit_events"):
        op.execute(
            f"CREATE TRIGGER immutable_action_history BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_action_history()"
        )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    for table in ("action_audit_events", "action_executions"):
        op.execute(f"DROP TRIGGER immutable_action_history ON {table}")
    op.execute("DROP FUNCTION protect_action_history()")
    op.drop_table("webhook_attempts")
    op.drop_index("ix_outbox_pending", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_table("edit_overlays")
    op.drop_index("ix_action_audit_object", table_name="action_audit_events")
    op.drop_table("action_audit_events")
    op.drop_index("ix_reconciliation_object", table_name="reconciliation_conflicts")
    op.drop_table("reconciliation_conflicts")
    op.drop_index("ix_action_history", table_name="action_executions")
    op.drop_table("action_executions")
