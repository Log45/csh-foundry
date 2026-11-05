"""Governed media, trusted functions and durable automations. Forward-only."""

from alembic import op

revision = "0023_media_functions"
down_revision = "0022_materialization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.execute("""CREATE TABLE governed_definitions (
    tenant_id UUID NOT NULL,
    resource_id UUID NOT NULL,
    id UUID NOT NULL,
    kind VARCHAR(20) NOT NULL,
    target_resource_id UUID,
    target_definition_id UUID,
    event_resource_id UUID,
    sequence INTEGER NOT NULL,
    specification JSONB NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (tenant_id, resource_id, id),
    FOREIGN KEY(tenant_id, resource_id) REFERENCES platform_resources (tenant_id, id),
    FOREIGN KEY(tenant_id, target_resource_id, target_definition_id) REFERENCES
        governed_definitions (tenant_id, resource_id, id),
    FOREIGN KEY(tenant_id, event_resource_id) REFERENCES platform_resources (tenant_id, id),
    CONSTRAINT ck_governed_target CHECK ((kind='AUTOMATION' AND target_resource_id IS NOT NULL AND
        target_definition_id IS NOT NULL) OR (kind<>'AUTOMATION' AND target_resource_id IS NULL
        AND target_definition_id IS NULL AND event_resource_id IS NULL)),
    CONSTRAINT uq_governed_sequence UNIQUE (tenant_id, resource_id, sequence),
    CONSTRAINT ck_governed_sequence CHECK (sequence > 0),
    CONSTRAINT ck_governed_kind CHECK (kind IN ('MEDIA_SET','FUNCTION','AUTOMATION')),
    CONSTRAINT ck_governed_bytes CHECK (octet_length(specification::text) <= 524288)
)""")
    op.execute("""CREATE TABLE media_items (
    tenant_id UUID NOT NULL,
    set_id UUID NOT NULL,
    id UUID NOT NULL,
    artifact_id UUID NOT NULL,
    artifact_version_id UUID NOT NULL,
    media_type VARCHAR(100) NOT NULL,
    size BIGINT NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    filename TEXT NOT NULL,
    metadata JSONB NOT NULL,
    preview_artifact_id UUID,
    preview_version_id UUID,
    created_by TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (tenant_id, set_id, id),
    FOREIGN KEY(tenant_id, set_id) REFERENCES platform_resources (tenant_id, id),
        FOREIGN KEY(tenant_id, artifact_id, artifact_version_id) REFERENCES artifact_versions
        (tenant_id, artifact_id, id),
        FOREIGN KEY(tenant_id, preview_artifact_id, preview_version_id) REFERENCES
        artifact_versions (tenant_id, artifact_id, id),
    CONSTRAINT uq_media_source UNIQUE (tenant_id, set_id, artifact_id, artifact_version_id),
    CONSTRAINT ck_media_size CHECK (size >= 0),
        CONSTRAINT ck_media_type CHECK (media_type IN
        ('image/png','image/jpeg','audio/wav','video/mp4','application/pdf')),
    CONSTRAINT ck_media_preview CHECK ((preview_artifact_id IS NULL) = (preview_version_id IS NULL))
)""")
    op.execute("""CREATE TABLE media_memberships (
    tenant_id UUID NOT NULL,
    set_id UUID NOT NULL,
    version_id UUID NOT NULL,
    item_id UUID NOT NULL,
    PRIMARY KEY (tenant_id, set_id, version_id, item_id),
        FOREIGN KEY(tenant_id, set_id, version_id) REFERENCES governed_definitions (tenant_id,
        resource_id, id),
    FOREIGN KEY(tenant_id, set_id, item_id) REFERENCES media_items (tenant_id, set_id, id)
)""")
    op.execute("""CREATE TABLE function_invocations (
    tenant_id UUID NOT NULL,
    job_id UUID NOT NULL,
    function_id UUID NOT NULL,
    definition_id UUID NOT NULL,
    key VARCHAR(64) NOT NULL,
    actor TEXT NOT NULL,
    inputs JSONB NOT NULL,
    PRIMARY KEY (tenant_id, job_id),
    FOREIGN KEY(tenant_id, job_id) REFERENCES execution_jobs (tenant_id, id),
        FOREIGN KEY(tenant_id, function_id, definition_id) REFERENCES governed_definitions
        (tenant_id, resource_id, id),
    CONSTRAINT uq_function_key UNIQUE (tenant_id, function_id, actor, key),
    CONSTRAINT ck_function_input_bytes CHECK (octet_length(inputs::text) <= 65536)
)""")
    op.execute("""CREATE TABLE function_results (
    tenant_id UUID NOT NULL,
    job_id UUID NOT NULL,
    definition_id UUID NOT NULL,
    values JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (tenant_id, job_id),
    FOREIGN KEY(tenant_id, job_id) REFERENCES function_invocations (tenant_id, job_id),
    CONSTRAINT ck_function_output_bytes CHECK (octet_length(values::text) <= 65536)
)""")
    op.execute("""CREATE TABLE automation_states (
    tenant_id UUID NOT NULL,
    automation_id UUID NOT NULL,
    definition_id UUID NOT NULL,
    enabled BOOLEAN NOT NULL,
    activation_id UUID NOT NULL,
    checked_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    next_run_at TIMESTAMP WITH TIME ZONE,
    event_time TIMESTAMP WITH TIME ZONE NOT NULL,
    event_id UUID NOT NULL,
    owner TEXT NOT NULL,
    principal JSONB NOT NULL,
    last_error VARCHAR(100),
    PRIMARY KEY (tenant_id, automation_id),
        FOREIGN KEY(tenant_id, automation_id, definition_id) REFERENCES governed_definitions
        (tenant_id, resource_id, id)
)""")
    op.execute("""CREATE INDEX ix_automation_due ON automation_states (enabled, next_run_at)""")
    op.execute("""CREATE TABLE automation_receipts (
    tenant_id UUID NOT NULL,
    automation_id UUID NOT NULL,
    id UUID NOT NULL,
    definition_id UUID NOT NULL,
    dedup_key VARCHAR(200) NOT NULL,
    trigger_kind VARCHAR(30) NOT NULL,
    trigger_at TIMESTAMP WITH TIME ZONE NOT NULL,
    job_id UUID,
    error VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (tenant_id, automation_id, id),
        FOREIGN KEY(tenant_id, automation_id, definition_id) REFERENCES governed_definitions
        (tenant_id, resource_id, id),
    FOREIGN KEY(tenant_id, job_id) REFERENCES execution_jobs (tenant_id, id),
    CONSTRAINT uq_automation_trigger UNIQUE (tenant_id, automation_id, dedup_key),
    CONSTRAINT ck_automation_outcome CHECK ((job_id IS NULL) <> (error IS NULL))
)""")
    op.drop_constraint("ck_resource_type", "platform_resources", type_="check")
    op.create_check_constraint(
        "ck_resource_type",
        "platform_resources",
        """resource_type IN
        ('ONTOLOGY_OBJECT_TYPE','ONTOLOGY_LINK_TYPE','ONTOLOGY_ACTION','ONTOLOGY_VERSION',
        'ARTIFACT','DATASET','PIPELINE','MAPPING','MEDIA_SET','FUNCTION','AUTOMATION')""",
    )
    op.drop_constraint("ck_resource_authority_kind", "platform_resources", type_="check")
    op.create_check_constraint(
        "ck_resource_authority_kind",
        "platform_resources",
        """(resource_type IN
        ('ARTIFACT','DATASET','PIPELINE','MAPPING','MEDIA_SET','FUNCTION','AUTOMATION') AND
        ontology_id IS NULL AND schema_version IS NULL AND entity_id IS NULL) OR (resource_type
        NOT IN ('ARTIFACT','DATASET','PIPELINE','MAPPING','MEDIA_SET','FUNCTION','AUTOMATION') AND
        ontology_id IS NOT NULL AND schema_version IS NOT NULL AND entity_id IS NOT NULL)""",
    )
    op.drop_constraint("ck_execution_kind", "execution_jobs", type_="check")
    op.create_check_constraint(
        "ck_execution_kind",
        "execution_jobs",
        """kind IN ('VALIDATION','PIPELINE','MATERIALIZATION','FUNCTION')""",
    )
    op.drop_constraint("ck_execution_contract", "execution_jobs", type_="check")
    op.create_check_constraint(
        "ck_execution_contract",
        "execution_jobs",
        """(kind = 'VALIDATION' AND validation_version_id IS NOT NULL AND definition_id IS NULL
        AND mapping_definition_id IS NULL AND output_dataset_id IS NULL) OR (kind = 'PIPELINE' AND
        definition_id IS NOT NULL AND validation_version_id IS NULL AND mapping_definition_id IS
        NULL AND output_dataset_id IS NOT NULL) OR (kind = 'MATERIALIZATION' AND
        mapping_definition_id IS NOT NULL AND definition_id IS NULL AND validation_version_id IS
        NULL AND output_dataset_id IS NULL) OR (kind = 'FUNCTION' AND definition_id IS NULL AND
        mapping_definition_id IS NULL AND validation_version_id IS NULL AND output_dataset_id IS
        NULL)""",
    )
    op.execute("""DO $$ DECLARE body text; BEGIN
        SELECT pg_get_functiondef('validate_platform_resource()'::regprocedure) INTO body;
        EXECUTE replace(body, '''MAPPING'')',
            '''MAPPING'',''MEDIA_SET'',''FUNCTION'',''AUTOMATION'')');
        SELECT pg_get_functiondef('guard_artifact_version()'::regprocedure) INTO body;
        EXECUTE replace(body, '''ARTIFACT'',''DATASET'')',
            '''ARTIFACT'',''DATASET'',''MEDIA_SET'')');
        SELECT pg_get_functiondef('guard_execution_job()'::regprocedure) INTO body;
        EXECUTE replace(body, 'WHEN ''MATERIALIZATION'' THEN ''MAPPING''',
            'WHEN ''FUNCTION'' THEN ''FUNCTION'' WHEN ''MATERIALIZATION'' THEN ''MAPPING''');
    END $$""")
    op.execute("""CREATE FUNCTION guard_g_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE item jsonb; source artifact_versions; invocation_job execution_jobs;
    BEGIN
        IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'Published metadata is immutable' USING ERRCODE='23514';
        END IF;
        item := to_jsonb(NEW);
        IF TG_TABLE_NAME='governed_definitions' THEN
          IF NOT EXISTS (
            SELECT 1 FROM platform_resources WHERE tenant_id=NEW.tenant_id
            AND id=NEW.resource_id AND resource_type=NEW.kind AND state='ACTIVE'
        ) THEN
            RAISE EXCEPTION 'Definition authority mismatch' USING ERRCODE='23514';
          END IF;
          IF NEW.kind='AUTOMATION' THEN
            IF (NEW.target_resource_id::text, NEW.target_definition_id::text,
                NEW.event_resource_id::text) IS DISTINCT FROM
               (NEW.specification->>'function_id', NEW.specification->>'function_definition_id',
                NEW.specification->'trigger'->>'ontology_resource_id') OR NOT EXISTS (
                    SELECT 1 FROM governed_definitions WHERE tenant_id=NEW.tenant_id
                    AND resource_id=NEW.target_resource_id AND id=NEW.target_definition_id
                    AND kind='FUNCTION'
                ) THEN RAISE EXCEPTION 'Automation target mismatch' USING ERRCODE='23514'; END IF;
          END IF;
        ELSIF TG_TABLE_NAME='media_items' THEN
            SELECT * INTO source FROM artifact_versions WHERE tenant_id=NEW.tenant_id
                AND artifact_id=NEW.artifact_id AND id=NEW.artifact_version_id;
            IF source.state IS DISTINCT FROM 'COMMITTED'
                OR (source.size, source.checksum, source.filename) IS DISTINCT FROM
                   (NEW.size, NEW.checksum, NEW.filename)
                OR NOT EXISTS (SELECT 1 FROM platform_resources WHERE tenant_id=NEW.tenant_id
                    AND id=NEW.set_id AND resource_type='MEDIA_SET')
                OR NOT EXISTS (SELECT 1 FROM platform_resources WHERE tenant_id=NEW.tenant_id
                    AND id=NEW.artifact_id AND resource_type='ARTIFACT')
            THEN RAISE EXCEPTION 'Invalid media source' USING ERRCODE='23514'; END IF;
            IF NEW.preview_version_id IS NOT NULL AND
                (NEW.preview_artifact_id <> NEW.set_id OR NOT EXISTS (
                SELECT 1 FROM artifact_versions WHERE tenant_id=NEW.tenant_id
                AND artifact_id=NEW.preview_artifact_id AND id=NEW.preview_version_id
                AND state='COMMITTED'
            )) THEN RAISE EXCEPTION 'Invalid preview' USING ERRCODE='23514'; END IF;
        ELSIF TG_TABLE_NAME='media_memberships' THEN
          IF NOT EXISTS (
            SELECT 1 FROM governed_definitions WHERE tenant_id=NEW.tenant_id
            AND resource_id=NEW.set_id AND id=NEW.version_id AND kind='MEDIA_SET'
            AND specification->'items' @> jsonb_build_array(NEW.item_id::text)
            AND xmin::text=pg_current_xact_id()::text
        ) THEN
            RAISE EXCEPTION 'Snapshot membership is frozen' USING ERRCODE='23514';
          END IF;
        ELSIF TG_TABLE_NAME='function_invocations' THEN
            SELECT * INTO invocation_job FROM execution_jobs
                WHERE tenant_id=NEW.tenant_id AND id=NEW.job_id;
            IF invocation_job.kind IS DISTINCT FROM 'FUNCTION' OR invocation_job.state <> 'QUEUED'
               OR invocation_job.resource_id <> NEW.function_id
               OR invocation_job.principal->>'principal_id' <> NEW.actor
               OR invocation_job.request->>'definition_id' <> NEW.definition_id::text
               OR invocation_job.request->'inputs' IS DISTINCT FROM NEW.inputs
               OR NOT EXISTS (SELECT 1 FROM governed_definitions WHERE tenant_id=NEW.tenant_id
                   AND resource_id=NEW.function_id AND id=NEW.definition_id AND kind='FUNCTION')
            THEN RAISE EXCEPTION 'Invalid function invocation' USING ERRCODE='23514'; END IF;
        ELSIF TG_TABLE_NAME='function_results' THEN
            IF NOT EXISTS (
                SELECT 1 FROM execution_jobs e JOIN function_invocations i
                ON i.tenant_id=e.tenant_id AND i.job_id=e.id
                WHERE e.tenant_id=NEW.tenant_id AND e.id=NEW.job_id AND e.kind='FUNCTION'
                AND e.state='RUNNING' AND e.lease_until>clock_timestamp()
                AND e.token::text=current_setting('foundry.execution_token',true)
                AND i.definition_id=NEW.definition_id
            ) THEN RAISE EXCEPTION 'Result requires live fence' USING ERRCODE='23514'; END IF;
        ELSIF TG_TABLE_NAME='automation_receipts' THEN
            IF NOT EXISTS (SELECT 1 FROM governed_definitions WHERE tenant_id=NEW.tenant_id
                AND resource_id=NEW.automation_id AND id=NEW.definition_id AND kind='AUTOMATION')
            THEN RAISE EXCEPTION 'Invalid automation' USING ERRCODE='23514'; END IF;
            IF NEW.job_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM execution_jobs j JOIN governed_definitions d
                ON d.tenant_id=j.tenant_id AND d.resource_id=NEW.automation_id
                AND d.id=NEW.definition_id
                WHERE j.tenant_id=NEW.tenant_id AND j.id=NEW.job_id AND j.kind='FUNCTION'
                AND j.resource_id=d.target_resource_id
                AND j.request->>'definition_id'=d.target_definition_id::text
                AND j.request->'automation'->>'resource_id'=NEW.automation_id::text
                AND j.request->'automation'->>'definition_id'=NEW.definition_id::text
            ) THEN RAISE EXCEPTION 'Invalid automation job' USING ERRCODE='23514'; END IF;
        END IF;
        RETURN NEW;
    END $$""")
    for table in (
        "governed_definitions",
        "media_items",
        "media_memberships",
        "function_invocations",
        "function_results",
        "automation_receipts",
    ):
        op.execute(
            f"CREATE TRIGGER guard_{table} BEFORE INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION guard_g_immutable()"
        )
    op.execute("""CREATE FUNCTION guard_function_success() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.kind='FUNCTION' AND NEW.state='SUCCEEDED' AND NOT EXISTS (
            SELECT 1 FROM function_results WHERE tenant_id=NEW.tenant_id AND job_id=NEW.id
        ) THEN RAISE EXCEPTION 'Function success requires result' USING ERRCODE='23514'; END IF;
        RETURN NEW;
    END $$""")
    op.execute("""CREATE TRIGGER guard_function_success BEFORE UPDATE ON execution_jobs
        FOR EACH ROW EXECUTE FUNCTION guard_function_success()""")

    op.execute("""CREATE FUNCTION guard_automation_state() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP='DELETE' THEN
            RAISE EXCEPTION 'Automation state must be disabled, not deleted' USING ERRCODE='23514';
        END IF;
        IF TG_OP='UPDATE' THEN
            IF (OLD.tenant_id, OLD.automation_id, OLD.owner) IS DISTINCT FROM
               (NEW.tenant_id, NEW.automation_id, NEW.owner) THEN
                RAISE EXCEPTION 'Automation owner is immutable' USING ERRCODE='23514';
            END IF;
        END IF;
        IF NEW.principal->>'principal_id' IS DISTINCT FROM NEW.owner OR
           NEW.principal->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR NOT EXISTS (
            SELECT 1 FROM governed_definitions d WHERE d.tenant_id=NEW.tenant_id
            AND d.resource_id=NEW.automation_id AND d.id=NEW.definition_id AND d.kind='AUTOMATION'
            AND ((NOT NEW.enabled AND NEW.next_run_at IS NULL) OR
                 (NEW.enabled AND ((d.specification->'trigger'->>'kind' IN ('interval','daily'))
                    = (NEW.next_run_at IS NOT NULL))))
        ) THEN RAISE EXCEPTION 'Invalid automation binding' USING ERRCODE='23514'; END IF;
        RETURN NEW;
    END $$""")
    op.execute("""CREATE TRIGGER guard_automation_state BEFORE INSERT OR UPDATE OR DELETE
        ON automation_states FOR EACH ROW EXECUTE FUNCTION guard_automation_state()""")


def downgrade() -> None:
    raise RuntimeError("Media and execution history are forward-only; restore a verified backup")
