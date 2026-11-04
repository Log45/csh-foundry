"""Governed immutable pipeline definitions and fenced execution leases (forward-only)."""

from alembic import op

revision = "0021_execution"
down_revision = "0020_datasets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.drop_constraint("ck_resource_type", "platform_resources", type_="check")
    op.create_check_constraint(
        "ck_resource_type",
        "platform_resources",
        "resource_type IN "
        "('ONTOLOGY_OBJECT_TYPE','ONTOLOGY_LINK_TYPE','ONTOLOGY_ACTION','ONTOLOGY_VERSION','ARTIFACT','DATASET','PIPELINE')",
    )
    op.drop_constraint("ck_resource_authority_kind", "platform_resources", type_="check")
    op.create_check_constraint(
        "ck_resource_authority_kind",
        "platform_resources",
        "(resource_type IN ('ARTIFACT','DATASET','PIPELINE') AND ontology_id IS NULL AND "
        "schema_version IS NULL AND entity_id IS NULL) OR (resource_type NOT IN "
        "('ARTIFACT','DATASET','PIPELINE') AND ontology_id IS NOT NULL AND schema_version"
        " IS NOT NULL AND entity_id IS NOT NULL)",
    )
    op.execute("""DO $$ DECLARE body text; BEGIN
        SELECT pg_get_functiondef('validate_platform_resource()'::regprocedure) INTO body;
        body := replace(body, 'NEW.resource_type IN (''ARTIFACT'',''DATASET'')',
                              'NEW.resource_type IN (''ARTIFACT'',''DATASET'',''PIPELINE'')');
        EXECUTE body;
    END $$""")
    op.execute("""
CREATE TABLE pipeline_definitions (
	tenant_id UUID NOT NULL,
	pipeline_id UUID NOT NULL,
	id UUID NOT NULL,
	sequence INTEGER NOT NULL,
	specification JSONB NOT NULL,
	created_by TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (tenant_id, pipeline_id, id),
	FOREIGN KEY(tenant_id, pipeline_id) REFERENCES platform_resources (tenant_id, id),
	CONSTRAINT uq_pipeline_sequence UNIQUE (tenant_id, pipeline_id, sequence),
	CONSTRAINT ck_pipeline_sequence CHECK (sequence > 0)
)

""")
    op.execute("""
CREATE TABLE execution_jobs (
	tenant_id UUID NOT NULL,
	id UUID NOT NULL,
	resource_id UUID NOT NULL,
	project_id UUID NOT NULL,
	kind VARCHAR(20) NOT NULL,
	definition_id UUID,
	validation_version_id UUID,
	output_dataset_id UUID,
	output_version_id UUID,
	request JSONB NOT NULL,
	principal JSONB NOT NULL,
	limits JSONB NOT NULL,
	state VARCHAR(20) NOT NULL,
	attempts INTEGER NOT NULL,
	token UUID,
	lease_until TIMESTAMP WITH TIME ZONE,
	error VARCHAR(100),
	metrics JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	admitted_at TIMESTAMP WITH TIME ZONE,
	started_at TIMESTAMP WITH TIME ZONE,
	heartbeat_at TIMESTAMP WITH TIME ZONE,
	completed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (tenant_id, id),
	FOREIGN KEY(tenant_id, resource_id) REFERENCES platform_resources (tenant_id, id),
	FOREIGN KEY(tenant_id, project_id) REFERENCES projects (tenant_id, id),
        FOREIGN KEY(tenant_id, resource_id, definition_id) REFERENCES pipeline_definitions
(tenant_id, pipeline_id, id),
        FOREIGN KEY(tenant_id, resource_id, validation_version_id) REFERENCES dataset_versions
(tenant_id, artifact_id, id),
        FOREIGN KEY(tenant_id, output_dataset_id, output_version_id) REFERENCES dataset_versions
(tenant_id, artifact_id, id),
	CONSTRAINT uq_dataset_validation_job UNIQUE (tenant_id, resource_id, validation_version_id),
	CONSTRAINT uq_run_output UNIQUE (tenant_id, output_dataset_id, output_version_id),
	CONSTRAINT ck_execution_kind CHECK (kind IN ('VALIDATION','PIPELINE')),
        CONSTRAINT ck_execution_state CHECK (state IN
('QUEUED','ADMITTED','RUNNING','CANCELLING','SUCCEEDED','FAILED','CANCELLED')),
	CONSTRAINT ck_execution_attempts CHECK (attempts >= 0),
        CONSTRAINT ck_execution_completed CHECK ((state IN ('SUCCEEDED','FAILED','CANCELLED')) =
(completed_at IS NOT NULL)),
        CONSTRAINT ck_execution_contract CHECK ((kind = 'VALIDATION' AND validation_version_id
IS NOT NULL AND definition_id IS NULL AND output_dataset_id IS NULL) OR (kind = 'PIPELINE' AND
definition_id IS NOT NULL AND validation_version_id IS NULL AND output_dataset_id IS NOT NULL))
)

""")
    op.execute("""CREATE INDEX ix_execution_queue ON execution_jobs (state, created_at)""")
    op.execute("""
CREATE TABLE execution_inputs (
	tenant_id UUID NOT NULL,
	job_id UUID NOT NULL,
	name VARCHAR(200) NOT NULL,
	dataset_id UUID NOT NULL,
	version_id UUID NOT NULL,
	checksum VARCHAR(64) NOT NULL,
	PRIMARY KEY (tenant_id, job_id, name),
	FOREIGN KEY(tenant_id, job_id) REFERENCES execution_jobs (tenant_id, id),
        FOREIGN KEY(tenant_id, dataset_id, version_id) REFERENCES dataset_versions (tenant_id,
artifact_id, id)
)

""")
    op.create_check_constraint(
        "ck_execution_lease",
        "execution_jobs",
        "(state IN ('ADMITTED','RUNNING','CANCELLING')) = "
        "(token IS NOT NULL AND lease_until IS NOT NULL)",
    )
    op.create_foreign_key(
        None,
        "execution_jobs",
        "platform_resources",
        ["tenant_id", "output_dataset_id"],
        ["tenant_id", "id"],
    )
    op.execute("""CREATE FUNCTION guard_pipeline_definition() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'Published definitions are immutable' USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM platform_resources WHERE tenant_id = NEW.tenant_id
            AND id = NEW.pipeline_id AND resource_type = 'PIPELINE') THEN
            RAISE EXCEPTION 'Definition requires PIPELINE authority' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END $$""")
    op.execute("""CREATE TRIGGER guard_pipeline_definition BEFORE INSERT OR UPDATE OR DELETE
        ON pipeline_definitions FOR EACH ROW EXECUTE FUNCTION guard_pipeline_definition()""")
    op.execute("""CREATE FUNCTION guard_execution_job() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Execution history is immutable' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' THEN
            IF (OLD.tenant_id, OLD.id, OLD.resource_id, OLD.project_id, OLD.kind,
                OLD.definition_id, OLD.validation_version_id, OLD.output_dataset_id,
                OLD.request, OLD.principal, OLD.limits, OLD.created_at) IS DISTINCT FROM
               (NEW.tenant_id, NEW.id, NEW.resource_id, NEW.project_id, NEW.kind,
                NEW.definition_id, NEW.validation_version_id, NEW.output_dataset_id,
                NEW.request, NEW.principal, NEW.limits, NEW.created_at) THEN
                RAISE EXCEPTION 'Execution contract is immutable' USING ERRCODE = '23514';
            END IF;
            IF OLD.state IN ('SUCCEEDED','CANCELLED') OR
               (OLD.state = 'FAILED' AND NEW.state <> 'QUEUED') THEN
                RAISE EXCEPTION 'Terminal execution is immutable' USING ERRCODE = '23514';
            END IF;
            IF OLD.state <> NEW.state AND NOT (
                (OLD.state = 'QUEUED' AND NEW.state IN ('ADMITTED','CANCELLED','FAILED')) OR
                (OLD.state = 'ADMITTED' AND NEW.state IN
('RUNNING','QUEUED','CANCELLING','FAILED')) OR
                (OLD.state = 'RUNNING' AND NEW.state IN
('SUCCEEDED','FAILED','CANCELLING','QUEUED')) OR
                (OLD.state = 'CANCELLING' AND NEW.state = 'CANCELLED') OR
                (OLD.state = 'FAILED' AND NEW.state = 'QUEUED')) THEN
                RAISE EXCEPTION 'Invalid execution transition' USING ERRCODE = '23514';
            END IF;
            IF OLD.output_version_id IS NOT NULL AND NEW.output_version_id IS DISTINCT FROM
OLD.output_version_id THEN
                RAISE EXCEPTION 'Output reservation is immutable' USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.state <> 'QUEUED' OR NEW.attempts <> 0 THEN
            RAISE EXCEPTION 'Execution must start queued' USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM platform_resources WHERE tenant_id = NEW.tenant_id
            AND id = NEW.resource_id AND project_id = NEW.project_id AND
            resource_type = CASE NEW.kind WHEN 'PIPELINE' THEN 'PIPELINE' ELSE 'DATASET' END) THEN
            RAISE EXCEPTION 'Execution requires matching resource authority' USING ERRCODE =
'23514';
        END IF;
        IF NEW.state = 'SUCCEEDED' AND NEW.kind = 'PIPELINE' AND NOT EXISTS (
            SELECT 1 FROM dataset_versions WHERE tenant_id = NEW.tenant_id
            AND artifact_id = NEW.output_dataset_id AND id = NEW.output_version_id AND state =
'COMMITTED') THEN
            RAISE EXCEPTION 'Success requires committed output' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END $$""")
    op.execute("""CREATE TRIGGER guard_execution_job BEFORE INSERT OR UPDATE OR DELETE
        ON execution_jobs FOR EACH ROW EXECUTE FUNCTION guard_execution_job()""")
    op.execute("""CREATE FUNCTION guard_execution_input() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'Input lineage is immutable' USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM execution_jobs WHERE tenant_id = NEW.tenant_id
            AND id = NEW.job_id AND kind = 'PIPELINE' AND state = 'QUEUED') THEN
            RAISE EXCEPTION 'Inputs are fixed at admission' USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM dataset_versions d JOIN artifact_versions a USING
(tenant_id, artifact_id, id)
            WHERE d.tenant_id = NEW.tenant_id AND d.artifact_id = NEW.dataset_id
            AND d.id = NEW.version_id AND d.state = 'COMMITTED' AND a.state = 'COMMITTED'
            AND a.checksum = NEW.checksum) THEN
            RAISE EXCEPTION 'Input must pin committed verified dataset' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END $$""")
    op.execute("""CREATE TRIGGER guard_execution_input BEFORE INSERT OR UPDATE OR DELETE
        ON execution_inputs FOR EACH ROW EXECUTE FUNCTION guard_execution_input()""")

    op.execute("""CREATE FUNCTION require_execution_publication(t uuid, r uuid, v uuid)
        RETURNS void LANGUAGE plpgsql AS $$ BEGIN
        IF EXISTS (SELECT 1 FROM execution_jobs WHERE tenant_id=t AND output_dataset_id=r
            AND output_version_id=v) AND NOT EXISTS (
            SELECT 1 FROM execution_jobs WHERE tenant_id=t AND output_dataset_id=r
            AND output_version_id=v AND state='RUNNING' AND lease_until > clock_timestamp()
            AND token::text=current_setting('foundry.execution_token', true)) THEN
            RAISE EXCEPTION 'Pipeline output requires live fenced publication'
                USING ERRCODE='23514';
        END IF;
    END $$""")
    # Extend existing guards additively; historical migrations and ordinary uploads stay intact.
    op.execute("""DO $$ DECLARE body text; target text; position integer; BEGIN
        FOREACH target IN ARRAY ARRAY['guard_artifact_version', 'guard_dataset_version'] LOOP
            SELECT pg_get_functiondef((target || '()')::regprocedure) INTO body;
            position := strpos(body, 'BEGIN');
            body := overlay(body placing 'BEGIN
                IF TG_OP <> ''DELETE'' AND NEW.state = ''COMMITTED'' THEN
                    PERFORM require_execution_publication(NEW.tenant_id, NEW.artifact_id, NEW.id);
                END IF;' from position for 5);
            EXECUTE body;
        END LOOP;
    END $$""")


def downgrade() -> None:
    raise RuntimeError("Execution history is forward-only; restore a verified backup")
