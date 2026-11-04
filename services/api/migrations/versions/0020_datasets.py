"""Independent dataset snapshots; forward-only after immutable artifacts."""

import sqlalchemy as sa
from alembic import op

revision = "0020_datasets"
down_revision = "0019_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.drop_constraint("ck_resource_type", "platform_resources", type_="check")
    op.create_check_constraint(
        "ck_resource_type",
        "platform_resources",
        "resource_type IN "
        "('ONTOLOGY_OBJECT_TYPE','ONTOLOGY_LINK_TYPE','ONTOLOGY_ACTION','ONTOLOGY_VERSION',"
        "'ARTIFACT','DATASET')",
    )
    op.drop_constraint("ck_resource_authority_kind", "platform_resources", type_="check")
    op.create_check_constraint(
        "ck_resource_authority_kind",
        "platform_resources",
        "(resource_type IN ('ARTIFACT','DATASET') AND ontology_id IS NULL AND schema_version "
        "IS NULL AND entity_id IS NULL) OR (resource_type NOT IN ('ARTIFACT','DATASET') AND "
        "ontology_id IS NOT NULL AND schema_version IS NOT NULL AND entity_id IS NOT NULL)",
    )
    # Preserve historical trigger definitions, extending only the admitted physical resource types.
    op.execute("""DO $$ DECLARE body text; BEGIN
        SELECT pg_get_functiondef('validate_platform_resource()'::regprocedure) INTO body;
        body := replace(body, 'NEW.resource_type = ''ARTIFACT''',
                              'NEW.resource_type IN (''ARTIFACT'',''DATASET'')');
        EXECUTE body;
        SELECT pg_get_functiondef('guard_artifact_version()'::regprocedure) INTO body;
        body := replace(body, 'resource_type = ''ARTIFACT''',
                              'resource_type IN (''ARTIFACT'',''DATASET'')');
        EXECUTE body;
    END $$""")
    op.create_table(
        "dataset_versions",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("format", sa.String(20), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("result", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("tenant_id", "artifact_id", "id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "artifact_id", "id"],
            [
                "artifact_versions.tenant_id",
                "artifact_versions.artifact_id",
                "artifact_versions.id",
            ],
        ),
        sa.CheckConstraint("format IN ('csv','json','ndjson','parquet')", name="ck_dataset_format"),
        sa.CheckConstraint("state IN ('PENDING','COMMITTED','FAILED')", name="ck_dataset_state"),
        sa.CheckConstraint(
            "(state IN ('COMMITTED','FAILED')) = (finalized_at IS NOT NULL)",
            name="ck_dataset_commit",
        ),
    )
    op.execute("""CREATE FUNCTION guard_dataset_version() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Dataset history is immutable' USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM platform_resources WHERE tenant_id = NEW.tenant_id
            AND id = NEW.artifact_id AND resource_type = 'DATASET') THEN
            RAISE EXCEPTION 'Dataset requires DATASET authority' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'INSERT' AND (NEW.state <> 'PENDING' OR NEW.result <> '{}'::jsonb) THEN
            RAISE EXCEPTION 'Dataset must begin pending' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' AND (OLD.state <> 'PENDING' OR
            (NEW.tenant_id, NEW.artifact_id, NEW.id, NEW.format) IS DISTINCT FROM
            (OLD.tenant_id, OLD.artifact_id, OLD.id, OLD.format) OR
            NEW.state NOT IN ('COMMITTED','FAILED')) THEN
            RAISE EXCEPTION 'Invalid dataset transition' USING ERRCODE = '23514';
        END IF;
        IF NEW.state IN ('COMMITTED','FAILED') AND NOT EXISTS (
            SELECT 1 FROM artifact_versions WHERE tenant_id = NEW.tenant_id
            AND artifact_id = NEW.artifact_id AND id = NEW.id AND state = 'COMMITTED') THEN
            RAISE EXCEPTION 'Validation requires committed artifact' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END $$""")
    op.execute("""CREATE TRIGGER guard_dataset_version BEFORE INSERT OR UPDATE OR DELETE
        ON dataset_versions FOR EACH ROW EXECUTE FUNCTION guard_dataset_version()""")


def downgrade() -> None:
    raise RuntimeError("Dataset history is forward-only; restore a verified backup")
