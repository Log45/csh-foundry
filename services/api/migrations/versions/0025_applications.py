"""Governed applications, private drafts and immutable publication. Forward-only."""

from alembic import op

revision = "0025_applications"
down_revision = "0024_pipeline_graphs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.drop_constraint("ck_resource_type", "platform_resources")
    op.drop_constraint("ck_resource_authority_kind", "platform_resources")
    kinds = (
        "'ARTIFACT','DATASET','PIPELINE','MAPPING','MEDIA_SET',"
        "'FUNCTION','AUTOMATION','APPLICATION'"
    )
    op.create_check_constraint(
        "ck_resource_type",
        "platform_resources",
        "resource_type IN ('ONTOLOGY_OBJECT_TYPE','ONTOLOGY_LINK_TYPE',"
        "'ONTOLOGY_ACTION','ONTOLOGY_VERSION'," + kinds + ")",
    )
    op.create_check_constraint(
        "ck_resource_authority_kind",
        "platform_resources",
        f"(resource_type IN ({kinds}) AND ontology_id IS NULL AND schema_version IS NULL "
        f"AND entity_id IS NULL) OR (resource_type NOT IN ({kinds}) AND ontology_id IS NOT NULL "
        "AND schema_version IS NOT NULL AND entity_id IS NOT NULL)",
    )
    op.execute("""DO $$ DECLARE body text; BEGIN
        SELECT pg_get_functiondef('validate_platform_resource()'::regprocedure) INTO body;
        EXECUTE replace(body, '''AUTOMATION'')', '''AUTOMATION'',''APPLICATION'')');
    END $$""")
    op.execute("""CREATE TABLE application_drafts (
        tenant_id UUID NOT NULL, application_id UUID NOT NULL, actor_id TEXT NOT NULL,
        revision INTEGER NOT NULL, document JSONB NOT NULL,
        PRIMARY KEY (tenant_id, application_id, actor_id),
        FOREIGN KEY (tenant_id, application_id) REFERENCES platform_resources (tenant_id, id),
        CONSTRAINT ck_application_draft_revision CHECK (revision > 0),
        CONSTRAINT ck_application_draft_bytes CHECK (octet_length(document::text) <= 131072)
    )""")
    op.execute("""CREATE TABLE application_versions (
        tenant_id UUID NOT NULL, application_id UUID NOT NULL, id UUID NOT NULL,
        sequence INTEGER NOT NULL, format_version INTEGER NOT NULL, document JSONB NOT NULL,
        digest VARCHAR(64) NOT NULL, manifest JSONB NOT NULL, created_by TEXT NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        PRIMARY KEY (tenant_id, application_id, id),
        FOREIGN KEY (tenant_id, application_id) REFERENCES platform_resources (tenant_id, id),
        CONSTRAINT uq_application_sequence UNIQUE (tenant_id, application_id, sequence),
        CONSTRAINT uq_application_digest UNIQUE (tenant_id, application_id, digest),
        CONSTRAINT ck_application_version CHECK (sequence > 0 AND format_version = 1),
        CONSTRAINT ck_application_version_bytes CHECK (octet_length(document::text) <= 131072)
    )""")
    op.execute("""CREATE FUNCTION immutable_application_version() RETURNS trigger LANGUAGE plpgsql
        AS $$ BEGIN RAISE EXCEPTION 'Published application versions are immutable'; END $$""")
    op.execute("""CREATE TRIGGER immutable_application_version BEFORE UPDATE OR DELETE
        ON application_versions FOR EACH ROW EXECUTE FUNCTION immutable_application_version()""")
    op.execute("""CREATE FUNCTION application_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM platform_resources r WHERE r.tenant_id=NEW.tenant_id
            AND r.id=NEW.application_id AND r.resource_type='APPLICATION' AND r.state='ACTIVE') THEN
            RAISE EXCEPTION 'An active application is required';
          END IF;
          IF TG_TABLE_NAME='application_drafts' AND TG_OP='UPDATE' THEN
            IF NEW.tenant_id<>OLD.tenant_id OR NEW.application_id<>OLD.application_id
                OR NEW.actor_id<>OLD.actor_id OR NEW.revision<>OLD.revision+1 THEN
              RAISE EXCEPTION 'Draft identity is fixed and revision must advance by one';
            END IF;
          END IF;
          RETURN NEW;
        END $$""")
    for table in ("application_drafts", "application_versions"):
        op.execute(
            f"CREATE TRIGGER application_guard BEFORE INSERT OR UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION application_guard()"
        )


def downgrade() -> None:
    raise RuntimeError("forward-only migration; restore an owned backup instead")
