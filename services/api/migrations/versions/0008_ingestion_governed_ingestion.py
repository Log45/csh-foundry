"""governed_ingestion"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_ingestion"
down_revision = "0007_edit_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        "ingestion_sources",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("definition_json", sa.Text(), nullable=False),
        sa.Column("binding_revision", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version >= 1", name="ck_ingestion_source_version"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id"],
            ["ontologies.tenant_id", "ontologies.id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "ontology_id", "id", "version"),
    )
    op.create_table(
        "ingestion_mappings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(length=100), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("definition_json", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version >= 1", name="ck_ingestion_mapping_version"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "schema_version"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "source_id", "source_version"],
            [
                "ingestion_sources.tenant_id",
                "ingestion_sources.ontology_id",
                "ingestion_sources.id",
                "ingestion_sources.version",
            ],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "ontology_id", "id", "version"),
    )
    op.create_table(
        "ingestion_runs",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("plan", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy", sa.String(length=20), nullable=False),
        sa.Column("batch_size", sa.Integer(), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("token", sa.Uuid(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("mapping_cursor", sa.Integer(), nullable=False),
        sa.Column("row_cursor", sa.Integer(), nullable=False),
        sa.Column("checkpoint", sa.Integer(), nullable=False),
        sa.Column("staged", sa.Integer(), nullable=False),
        sa.Column("staged_bytes", sa.Integer(), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False),
        sa.Column("created", sa.Integer(), nullable=False),
        sa.Column("updated", sa.Integer(), nullable=False),
        sa.Column("links_created", sa.Integer(), nullable=False),
        sa.Column("rejected", sa.Integer(), nullable=False),
        sa.Column("observed", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("last_error", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "phase IN ('STAGING','VALIDATING','OBJECTS','LINKS','DONE')", name="ck_ingestion_phase"
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="ck_ingestion_state",
        ),
        sa.CheckConstraint(
            "attempts BETWEEN 0 AND 3 AND batch_size BETWEEN 1 AND 100", name="ck_ingestion_budget"
        ),
        sa.CheckConstraint(
            "checkpoint >= 0 AND staged BETWEEN 0 AND 10000 "
            "AND staged_bytes BETWEEN 0 AND 16777216",
            name="ck_ingestion_checkpoint",
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
        sa.UniqueConstraint(
            "tenant_id", "ontology_id", "principal_id", "key_hash", name="uq_ingestion_request"
        ),
    )
    op.create_index(
        "ix_ingestion_history",
        "ingestion_runs",
        ["tenant_id", "ontology_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_ingestion_pending",
        "ingestion_runs",
        ["tenant_id", "status", "lease_until"],
        unique=False,
    )
    op.create_table(
        "source_object_identities",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("object_type", sa.Text(), nullable=False),
        sa.Column("object_id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.String(length=100), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "source_id", "source_version"],
            [
                "ingestion_sources.tenant_id",
                "ingestion_sources.ontology_id",
                "ingestion_sources.id",
                "ingestion_sources.version",
            ],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "ontology_id", "object_type", "object_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "ontology_id",
            "source_id",
            "namespace",
            "source_key",
            "object_type",
            name="uq_source_identity",
        ),
    )
    op.create_table(
        "ingestion_diagnostics",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "run_id"],
            ["ingestion_runs.tenant_id", "ingestion_runs.ontology_id", "ingestion_runs.id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "ontology_id", "id"),
    )
    op.create_index(
        "ix_ingestion_diagnostics_run",
        "ingestion_diagnostics",
        ["tenant_id", "ontology_id", "run_id"],
        unique=False,
    )
    op.create_table(
        "ingestion_stage",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("mapping_id", sa.String(length=100), nullable=False),
        sa.Column("mapping_version", sa.Integer(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=True),
        sa.Column("object_type", sa.Text(), nullable=False),
        sa.Column("object_id", sa.Text(), nullable=True),
        sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("relationships", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.CheckConstraint(
            "state IN ('STAGED','INVALID','OBJECT_DONE','DONE','REJECTED')",
            name="ck_ingestion_stage_state",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "mapping_id", "mapping_version"],
            [
                "ingestion_mappings.tenant_id",
                "ingestion_mappings.ontology_id",
                "ingestion_mappings.id",
                "ingestion_mappings.version",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "run_id"],
            ["ingestion_runs.tenant_id", "ingestion_runs.ontology_id", "ingestion_runs.id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "ontology_id", "run_id", "ordinal"),
        sa.UniqueConstraint(
            "tenant_id",
            "ontology_id",
            "run_id",
            "mapping_id",
            "mapping_version",
            "row_number",
            name="uq_stage_location",
        ),
    )
    op.create_index(
        "ix_ingestion_stage_identity",
        "ingestion_stage",
        ["tenant_id", "ontology_id", "run_id", "object_type", "object_id"],
        unique=False,
    )
    op.create_table(
        "source_link_state",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("object_type", sa.Text(), nullable=False),
        sa.Column("object_id", sa.Text(), nullable=False),
        sa.Column("link_type", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("managed", sa.Boolean(), nullable=False),
        sa.Column("edge_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "object_type", "object_id"],
            [
                "source_object_identities.tenant_id",
                "source_object_identities.ontology_id",
                "source_object_identities.object_type",
                "source_object_identities.object_id",
            ],
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "ontology_id", "object_type", "object_id", "link_type"
        ),
    )
    op.execute("""CREATE FUNCTION protect_ingestion_snapshot() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'ingestion configuration is immutable'
        USING ERRCODE='23514'; END $$""")
    for table in ("ingestion_sources", "ingestion_mappings"):
        op.execute(
            f"CREATE TRIGGER immutable_ingestion_snapshot BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_ingestion_snapshot()"
        )
    op.execute("""CREATE FUNCTION protect_ingestion_plan() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
        IF (NEW.tenant_id,NEW.ontology_id,NEW.id,NEW.schema_version,NEW.principal_id,NEW.plan,
            NEW.policy,NEW.batch_size,NEW.key_hash,NEW.request_hash) IS DISTINCT FROM
           (OLD.tenant_id,OLD.ontology_id,OLD.id,OLD.schema_version,OLD.principal_id,OLD.plan,
            OLD.policy,OLD.batch_size,OLD.key_hash,OLD.request_hash) THEN
            RAISE EXCEPTION 'ingestion plan is immutable' USING ERRCODE='23514';
        END IF; RETURN NEW; END $$""")
    op.execute(
        "CREATE TRIGGER immutable_ingestion_plan BEFORE UPDATE ON ingestion_runs "
        "FOR EACH ROW EXECUTE FUNCTION protect_ingestion_plan()"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.execute("DROP TRIGGER immutable_ingestion_plan ON ingestion_runs")
    op.execute("DROP FUNCTION protect_ingestion_plan()")
    for table in ("ingestion_mappings", "ingestion_sources"):
        op.execute(f"DROP TRIGGER immutable_ingestion_snapshot ON {table}")
    op.execute("DROP FUNCTION protect_ingestion_snapshot()")
    op.drop_table("source_link_state")
    op.drop_index("ix_ingestion_stage_identity", table_name="ingestion_stage")
    op.drop_table("ingestion_stage")
    op.drop_index("ix_ingestion_diagnostics_run", table_name="ingestion_diagnostics")
    op.drop_table("ingestion_diagnostics")
    op.drop_table("source_object_identities")
    op.drop_index("ix_ingestion_pending", table_name="ingestion_runs")
    op.drop_index("ix_ingestion_history", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
    op.drop_table("ingestion_mappings")
    op.drop_table("ingestion_sources")
