"""Governed immutable mappings and fenced materialization (forward-only)."""

import sqlalchemy as sa
from alembic import op

revision = "0022_materialization"
down_revision = "0021_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.execute("""
        CREATE TABLE mapping_definitions (
            tenant_id UUID NOT NULL,
            mapping_id UUID NOT NULL,
            id UUID NOT NULL,
            sequence INTEGER NOT NULL,
            target_resource_id UUID NOT NULL,
            ontology_id TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            specification JSONB NOT NULL,
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
            PRIMARY KEY (tenant_id, mapping_id, id),
            FOREIGN KEY (tenant_id, mapping_id) REFERENCES platform_resources (tenant_id, id),
            FOREIGN KEY (tenant_id, target_resource_id)
                REFERENCES platform_resources (tenant_id, id),
            FOREIGN KEY (tenant_id, ontology_id, schema_version)
                REFERENCES ontology_versions (tenant_id, ontology_id, version),
            CONSTRAINT uq_mapping_sequence UNIQUE (tenant_id, mapping_id, sequence),
            CONSTRAINT ck_mapping_sequence CHECK (sequence > 0)
        )
    """)
    # Ownership survives governed deletion as a tombstone; it must not prevent action deletes.
    op.execute("""
        CREATE TABLE mapping_ownership (
            tenant_id UUID NOT NULL,
            ontology_id TEXT NOT NULL,
            object_type TEXT NOT NULL,
            object_id TEXT NOT NULL,
            mapping_id UUID NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
            PRIMARY KEY (tenant_id, ontology_id, object_type, object_id),
            FOREIGN KEY (tenant_id, mapping_id) REFERENCES platform_resources (tenant_id, id),
            FOREIGN KEY (tenant_id, ontology_id) REFERENCES ontologies (tenant_id, id)
        )
    """)
    op.execute("""
        CREATE TABLE materialization_records (
            tenant_id UUID NOT NULL,
            run_id UUID NOT NULL,
            target_key VARCHAR(64) NOT NULL,
            target JSONB NOT NULL,
            source_record BIGINT NOT NULL,
            operation VARCHAR(20) NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
            PRIMARY KEY (tenant_id, run_id, target_key),
            FOREIGN KEY (tenant_id, run_id) REFERENCES execution_jobs (tenant_id, id),
            CONSTRAINT ck_materialization_operation
                CHECK (operation IN ('created','updated','preserved','observed')),
            CONSTRAINT ck_materialization_source CHECK (source_record > 0)
        )
    """)
    op.add_column("execution_jobs", sa.Column("mapping_definition_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        None,
        "execution_jobs",
        "mapping_definitions",
        ["tenant_id", "resource_id", "mapping_definition_id"],
        ["tenant_id", "mapping_id", "id"],
    )
    op.drop_constraint("ck_resource_type", "platform_resources", type_="check")
    op.create_check_constraint(
        "ck_resource_type",
        "platform_resources",
        "resource_type IN ('ONTOLOGY_OBJECT_TYPE','ONTOLOGY_LINK_TYPE','ONTOLOGY_ACTION',"
        "'ONTOLOGY_VERSION','ARTIFACT','DATASET','PIPELINE','MAPPING')",
    )
    op.drop_constraint("ck_resource_authority_kind", "platform_resources", type_="check")
    op.create_check_constraint(
        "ck_resource_authority_kind",
        "platform_resources",
        "(resource_type IN ('ARTIFACT','DATASET','PIPELINE','MAPPING') AND ontology_id IS NULL "
        "AND schema_version IS NULL AND entity_id IS NULL) OR (resource_type NOT IN "
        "('ARTIFACT','DATASET','PIPELINE','MAPPING') AND ontology_id IS NOT NULL "
        "AND schema_version IS NOT NULL AND entity_id IS NOT NULL)",
    )
    op.drop_constraint("ck_execution_kind", "execution_jobs", type_="check")
    op.create_check_constraint(
        "ck_execution_kind", "execution_jobs", "kind IN ('VALIDATION','PIPELINE','MATERIALIZATION')"
    )
    op.drop_constraint("ck_execution_contract", "execution_jobs", type_="check")
    op.create_check_constraint(
        "ck_execution_contract",
        "execution_jobs",
        "(kind = 'VALIDATION' AND validation_version_id IS NOT NULL AND definition_id IS NULL "
        "AND mapping_definition_id IS NULL AND output_dataset_id IS NULL) OR "
        "(kind = 'PIPELINE' AND definition_id IS NOT NULL AND mapping_definition_id IS NULL "
        "AND validation_version_id IS NULL AND output_dataset_id IS NOT NULL) OR "
        "(kind = 'MATERIALIZATION' AND mapping_definition_id IS NOT NULL AND definition_id IS NULL "
        "AND validation_version_id IS NULL AND output_dataset_id IS NULL)",
    )
    # Extend the frozen Phase 11/14 trigger definitions without importing evolving Python models.
    op.execute("""DO $$ DECLARE body text; BEGIN
        SELECT pg_get_functiondef('validate_platform_resource()'::regprocedure) INTO body;
        EXECUTE replace(body, '''PIPELINE'')', '''PIPELINE'',''MAPPING'')');
        SELECT pg_get_functiondef('guard_execution_job()'::regprocedure) INTO body;
        body := replace(body, 'OLD.definition_id,',
                              'OLD.mapping_definition_id, OLD.definition_id,');
        body := replace(body, 'NEW.definition_id,',
                              'NEW.mapping_definition_id, NEW.definition_id,');
        body := replace(body, 'WHEN ''PIPELINE'' THEN ''PIPELINE'' ELSE',
                              'WHEN ''MATERIALIZATION'' THEN ''MAPPING'' ' ||
                              'WHEN ''PIPELINE'' THEN ''PIPELINE'' ELSE');
        EXECUTE body;
        SELECT pg_get_functiondef('guard_execution_input()'::regprocedure) INTO body;
        EXECUTE replace(body, 'kind = ''PIPELINE''',
                              'kind IN (''PIPELINE'',''MATERIALIZATION'')');
    END $$""")
    op.execute("""CREATE FUNCTION guard_mapping_definition() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'Mapping definitions are immutable' USING ERRCODE='23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM platform_resources WHERE tenant_id=NEW.tenant_id
            AND id=NEW.mapping_id AND resource_type='MAPPING'
        ) OR NOT EXISTS (
            SELECT 1 FROM platform_resources r JOIN ontology_versions v
            ON v.tenant_id=r.tenant_id AND v.ontology_id=r.ontology_id
            AND v.version=r.schema_version
            WHERE r.tenant_id=NEW.tenant_id AND r.id=NEW.target_resource_id
            AND r.resource_type='ONTOLOGY_VERSION' AND r.ontology_id=NEW.ontology_id
            AND r.schema_version=NEW.schema_version AND v.status='PUBLISHED'
        ) THEN
            RAISE EXCEPTION 'Invalid mapping authority' USING ERRCODE='23514';
        END IF;
        IF (NEW.specification->>'ontology_id', NEW.specification->>'schema_version',
            NEW.specification->>'target_resource_id') IS DISTINCT FROM
           (NEW.ontology_id, NEW.schema_version, NEW.target_resource_id::text) THEN
            RAISE EXCEPTION 'Mapping target contract mismatch' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END $$""")
    op.execute("""CREATE TRIGGER guard_mapping_definition BEFORE INSERT OR UPDATE OR DELETE
        ON mapping_definitions FOR EACH ROW EXECUTE FUNCTION guard_mapping_definition()""")
    op.execute("""CREATE FUNCTION guard_materialization_record() RETURNS trigger
        LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'Materialization history and ownership are immutable'
                USING ERRCODE='23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM execution_jobs j WHERE j.tenant_id=NEW.tenant_id
            AND j.kind='MATERIALIZATION' AND j.state='RUNNING'
            AND j.lease_until>clock_timestamp()
            AND j.token::text=current_setting('foundry.execution_token', true)
            AND CASE WHEN TG_TABLE_NAME='materialization_records'
                THEN j.id=(to_jsonb(NEW)->>'run_id')::uuid
                ELSE j.resource_id=(to_jsonb(NEW)->>'mapping_id')::uuid END
        ) THEN
            RAISE EXCEPTION 'Materialization requires live fenced run' USING ERRCODE='23514';
        END IF;
        IF TG_TABLE_NAME='mapping_ownership' AND NOT EXISTS (
            SELECT 1 FROM objects o JOIN execution_jobs j ON j.tenant_id=o.tenant_id
            JOIN mapping_definitions d ON d.tenant_id=j.tenant_id
            AND d.mapping_id=j.resource_id AND d.id=j.mapping_definition_id
            WHERE o.tenant_id=NEW.tenant_id AND o.ontology_id=to_jsonb(NEW)->>'ontology_id'
            AND o.object_type_id=to_jsonb(NEW)->>'object_type'
            AND o.object_id=to_jsonb(NEW)->>'object_id'
            AND d.ontology_id=o.ontology_id
            AND j.resource_id=(to_jsonb(NEW)->>'mapping_id')::uuid
            AND j.token::text=current_setting('foundry.execution_token', true)
        ) THEN
            RAISE EXCEPTION 'Ownership requires canonical mapped object' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END $$""")
    for table in ("materialization_records", "mapping_ownership"):
        op.execute(
            f"CREATE TRIGGER guard_{table} BEFORE INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION guard_materialization_record()"
        )


def downgrade() -> None:
    raise RuntimeError("Materialization history is forward-only; restore a verified backup")
