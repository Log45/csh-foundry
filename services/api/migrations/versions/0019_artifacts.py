"""Generic immutable artifact versions; additive, forward-only after 0018_projects."""

import sqlalchemy as sa
from alembic import op

revision = "0019_artifacts"
down_revision = "0018_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    for column in ("ontology_id", "schema_version", "entity_id"):
        op.alter_column("platform_resources", column, existing_type=sa.Text(), nullable=True)
    op.drop_constraint("ck_resource_type", "platform_resources", type_="check")
    op.create_check_constraint(
        "ck_resource_type",
        "platform_resources",
        "resource_type IN ('ONTOLOGY_OBJECT_TYPE','ONTOLOGY_LINK_TYPE',"
        "'ONTOLOGY_ACTION','ONTOLOGY_VERSION','ARTIFACT')",
    )
    op.create_check_constraint(
        "ck_resource_authority_kind",
        "platform_resources",
        "(resource_type = 'ARTIFACT' AND ontology_id IS NULL AND schema_version IS NULL "
        "AND entity_id IS NULL) OR (resource_type <> 'ARTIFACT' AND ontology_id IS NOT NULL "
        "AND schema_version IS NOT NULL AND entity_id IS NOT NULL)",
    )
    op.execute("""
        CREATE OR REPLACE FUNCTION validate_platform_resource() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE definition jsonb; collection text;
        BEGIN
            IF TG_OP = 'UPDATE' AND
               (NEW.tenant_id, NEW.id, NEW.project_id, NEW.resource_type,
                NEW.ontology_id, NEW.schema_version, NEW.entity_id) IS DISTINCT FROM
               (OLD.tenant_id, OLD.id, OLD.project_id, OLD.resource_type,
                OLD.ontology_id, OLD.schema_version, OLD.entity_id) THEN
                RAISE EXCEPTION 'Resource authority and owning Project are immutable'
                   
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.resource_type = 'ARTIFACT' THEN RETURN NEW; END IF;
            SELECT definition_json::jsonb INTO definition FROM ontology_versions
            WHERE tenant_id = NEW.tenant_id AND ontology_id = NEW.ontology_id
              AND version = NEW.schema_version AND status = 'PUBLISHED';
            IF definition IS NULL THEN
                RAISE EXCEPTION 'Resource requires a published canonical version'
                   
                    USING ERRCODE = '23514';
            END IF;
            collection := CASE NEW.resource_type
                WHEN 'ONTOLOGY_OBJECT_TYPE' THEN 'object_types'
                WHEN 'ONTOLOGY_LINK_TYPE' THEN 'link_types'
                WHEN 'ONTOLOGY_ACTION' THEN 'action_types' END;
            IF (collection IS NULL AND NEW.entity_id <> NEW.schema_version) OR
               (collection IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM jsonb_array_elements(definition -> collection) item
                    WHERE item ->> 'id' = NEW.entity_id)) THEN
                RAISE EXCEPTION 'Unknown canonical resource reference'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)

    op.create_table(
        "artifact_versions",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("backend", sa.String(20), nullable=False),
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
        sa.Column("provenance", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "artifact_id", "id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "artifact_id"], ["platform_resources.tenant_id", "platform_resources.id"]
        ),
        sa.UniqueConstraint("tenant_id", "artifact_id", "sequence", name="uq_artifact_sequence"),
        sa.UniqueConstraint("backend", "bucket", "object_key", name="uq_artifact_object"),
        sa.CheckConstraint("sequence > 0 AND size >= 0", name="ck_artifact_size_sequence"),
        sa.CheckConstraint("checksum ~ '^[a-f0-9]{64}$'", name="ck_artifact_checksum"),
        sa.CheckConstraint(
            "state IN ('PENDING','COMMITTED','FAILED','DELETED')", name="ck_artifact_state"
        ),
        sa.CheckConstraint(
            "(state = 'COMMITTED') = (committed_at IS NOT NULL)", name="ck_artifact_commit"
        ),
    )
    op.execute("""
        CREATE FUNCTION guard_artifact_version() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Artifact version history cannot be deleted'
                    USING ERRCODE = '23514';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM platform_resources WHERE tenant_id = NEW.tenant_id
                AND id = NEW.artifact_id AND resource_type = 'ARTIFACT') THEN
                RAISE EXCEPTION 'Artifact requires ARTIFACT registry authority'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.object_key <> 'v1/' || NEW.tenant_id || '/' ||
                NEW.artifact_id || '/' || NEW.id THEN
                RAISE EXCEPTION 'Invalid immutable object key'
                    USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF OLD.state IN ('COMMITTED','DELETED') OR
                   (to_jsonb(NEW) - 'state' - 'committed_at') IS DISTINCT FROM
                   (to_jsonb(OLD) - 'state' - 'committed_at') OR
                   NOT ((OLD.state = 'PENDING' AND NEW.state IN ('COMMITTED','FAILED')) OR
                        (OLD.state = 'FAILED' AND NEW.state = 'DELETED')) THEN
                    RAISE EXCEPTION 'Immutable version or invalid transition'
                    USING ERRCODE = '23514';
                END IF;
            ELSIF NEW.state <> 'PENDING' THEN
                RAISE EXCEPTION 'Version must begin pending'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""CREATE TRIGGER guard_artifact_version BEFORE INSERT OR UPDATE OR DELETE
        ON artifact_versions FOR EACH ROW EXECUTE FUNCTION guard_artifact_version()""")


def downgrade() -> None:
    raise RuntimeError("Artifact metadata is forward-only; restore a verified backup")
