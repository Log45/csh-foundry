"""Immutable authoring import provenance and explicit vocabulary bindings."""

import sqlalchemy as sa
from alembic import op

revision = "0012_ontology_imports"
down_revision = "0011_semantic_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        "ontology_imports",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("draft_version", sa.Text(), nullable=True),
        sa.Column("canonical_hash", sa.String(64), nullable=True),
        sa.Column("bindings_json", sa.Text(), nullable=False),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("format", sa.String(20), nullable=False),
        sa.Column("original", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("graph", sa.Text(), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("diagnostics_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("tenant_id", "ontology_id", "id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id"], ["ontologies.tenant_id", "ontologies.id"]
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "draft_version"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
            ],
        ),
        sa.UniqueConstraint("tenant_id", "ontology_id", "draft_version", name="uq_import_draft"),
        sa.CheckConstraint("octet_length(bindings_json) <= 262144", name="ck_import_bindings"),
        sa.CheckConstraint("format IN ('turtle', 'rdfxml')", name="ck_import_format"),
        sa.CheckConstraint("octet_length(original) <= 262144", name="ck_import_bytes"),
        sa.CheckConstraint("octet_length(graph) <= 4194304", name="ck_import_graph"),
        sa.CheckConstraint("octet_length(result_json) <= 262144", name="ck_import_result"),
        sa.CheckConstraint("octet_length(request_json) <= 524288", name="ck_import_request"),
        sa.CheckConstraint(
            "octet_length(diagnostics_json) <= 4194304", name="ck_import_diagnostics"
        ),
    )
    op.create_table(
        "ontology_vocabulary_bindings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("iri_hash", sa.String(64), nullable=False),
        sa.Column("iri", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("target_hash", sa.String(64), nullable=False),
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "ontology_id", "iri_hash"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "import_id"],
            ["ontology_imports.tenant_id", "ontology_imports.ontology_id", "ontology_imports.id"],
        ),
        sa.UniqueConstraint("tenant_id", "ontology_id", "target_hash", name="uq_vocabulary_target"),
    )
    op.execute("""CREATE FUNCTION protect_ontology_import() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'ontology import provenance is immutable'; END $$""")
    for table in ("ontology_imports", "ontology_vocabulary_bindings"):
        op.execute(
            f"CREATE TRIGGER import_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_ontology_import()"
        )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.drop_table("ontology_vocabulary_bindings")
    op.drop_table("ontology_imports")
    op.execute("DROP FUNCTION protect_ontology_import()")
