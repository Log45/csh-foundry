"""semantic"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_semantic"
down_revision = "0009_ingestion_diagnostics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        "semantic_artifacts",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("output_hash", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN"
            " ('ontology','shapes','asserted','validation','reasoning','derived','change','proof')",
            name="ck_semantic_artifact_kind",
        ),
        sa.CheckConstraint("octet_length(content) <= 4194304", name="ck_semantic_artifact_size"),
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
            "tenant_id", "ontology_id", "principal_id", "fingerprint", name="uq_semantic_artifact"
        ),
    )
    op.create_table(
        "semantic_approvals",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("set_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint("state IN ('APPROVED','REJECTED')", name="ck_semantic_approval_state"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "set_id"],
            [
                "semantic_artifacts.tenant_id",
                "semantic_artifacts.ontology_id",
                "semantic_artifacts.id",
            ],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "ontology_id", "set_id", "id"),
    )
    op.create_table(
        "semantic_jobs",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("primary_artifact", sa.Uuid(), nullable=False),
        sa.Column("secondary_artifact", sa.Uuid(), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("token", sa.Uuid(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=100), nullable=True),
        sa.Column("outputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "status != 'RUNNING' OR (token IS NOT NULL AND lease_until IS NOT NULL)",
            name="ck_semantic_lease",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="ck_semantic_job_status",
        ),
        sa.CheckConstraint("attempts BETWEEN 0 AND 3", name="ck_semantic_attempts"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "primary_artifact"],
            [
                "semantic_artifacts.tenant_id",
                "semantic_artifacts.ontology_id",
                "semantic_artifacts.id",
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
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "secondary_artifact"],
            [
                "semantic_artifacts.tenant_id",
                "semantic_artifacts.ontology_id",
                "semantic_artifacts.id",
            ],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "ontology_id", "id"),
        sa.UniqueConstraint(
            "tenant_id", "ontology_id", "principal_id", "fingerprint", name="uq_semantic_job"
        ),
    )
    op.create_index(
        "ix_semantic_claim",
        "semantic_jobs",
        ["tenant_id", "ontology_id", "principal_id", "status", "created_at"],
        unique=False,
    )
    op.create_table(
        "semantic_derived_facts",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("set_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("predicate", sa.Text(), nullable=False),
        sa.Column("object", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "job_id"],
            ["semantic_jobs.tenant_id", "semantic_jobs.ontology_id", "semantic_jobs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "set_id"],
            [
                "semantic_artifacts.tenant_id",
                "semantic_artifacts.ontology_id",
                "semantic_artifacts.id",
            ],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "ontology_id", "set_id", "id"),
    )
    op.execute("""CREATE FUNCTION protect_semantic_immutable() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'semantic history is immutable'; END $$""")
    for table in ("semantic_artifacts", "semantic_derived_facts", "semantic_approvals"):
        op.execute(
            f"CREATE TRIGGER semantic_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_semantic_immutable()"
        )
    op.execute("""CREATE FUNCTION protect_semantic_plan() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF ROW(NEW.tenant_id, NEW.ontology_id, NEW.id, NEW.schema_version, NEW.principal_id,
             NEW.primary_artifact, NEW.secondary_artifact, NEW.request_json, NEW.fingerprint)
         IS DISTINCT FROM ROW(OLD.tenant_id, OLD.ontology_id, OLD.id,
             OLD.schema_version, OLD.principal_id,
             OLD.primary_artifact, OLD.secondary_artifact, OLD.request_json, OLD.fingerprint)
         OR OLD.status IN ('COMPLETED','FAILED','CANCELLED') THEN
        RAISE EXCEPTION 'semantic job plan or terminal state is immutable';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER semantic_plan BEFORE UPDATE ON semantic_jobs "
        "FOR EACH ROW EXECUTE FUNCTION protect_semantic_plan()"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.execute("DROP TRIGGER semantic_plan ON semantic_jobs")
    op.execute("DROP FUNCTION protect_semantic_plan()")
    for table in ("semantic_artifacts", "semantic_derived_facts", "semantic_approvals"):
        op.execute(f"DROP TRIGGER semantic_immutable ON {table}")
    op.execute("DROP FUNCTION protect_semantic_immutable()")
    op.drop_table("semantic_derived_facts")
    op.drop_index("ix_semantic_claim", table_name="semantic_jobs")
    op.drop_table("semantic_jobs")
    op.drop_table("semantic_approvals")
    op.drop_table("semantic_artifacts")
    # ### end Alembic commands ###
