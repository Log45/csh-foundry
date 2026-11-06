"""Durable DAG plans, fenced node results and atomic output manifests; forward-only."""

from alembic import op

revision = "0026_pipeline_dag"
down_revision = "0025_applications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.execute("""DO $$ DECLARE body text; BEGIN
      SELECT pg_get_constraintdef(oid) INTO body FROM pg_constraint
        WHERE conrelid='execution_jobs'::regclass AND conname='ck_execution_contract';
      ALTER TABLE execution_jobs DROP CONSTRAINT ck_execution_contract;
      body := replace(body, '(output_dataset_id IS NOT NULL)',
        '(output_dataset_id IS NOT NULL OR coalesce(request->>''format_version'','''')=''2'')');
      EXECUTE 'ALTER TABLE execution_jobs ADD CONSTRAINT ck_execution_contract ' || body;
      SELECT pg_get_functiondef('guard_execution_job()'::regprocedure) INTO body;
      body := replace(body, 'NEW.kind = ''PIPELINE'' AND NOT EXISTS',
        'NEW.kind = ''PIPELINE'' AND NEW.request->>''format_version'' ' ||
        'IS DISTINCT FROM ''2'' AND NOT EXISTS');
      EXECUTE body;
    END $$""")
    op.execute("""
    CREATE TABLE dag_runs (
      tenant_id uuid NOT NULL, job_id uuid NOT NULL,
      plan_digest varchar(64) NOT NULL, plan jsonb NOT NULL,
      state varchar(20) NOT NULL, commit_id uuid, cleaned_at timestamptz,
      execution_started_at timestamptz,
      PRIMARY KEY (tenant_id,job_id),
      FOREIGN KEY (tenant_id,job_id) REFERENCES execution_jobs(tenant_id,id),
      CONSTRAINT ck_dag_run_state CHECK (state IN
        ('EXECUTING','PREPARING','PREPARED','COMMITTED','ABANDONED')),
      CONSTRAINT ck_dag_commit CHECK ((state='COMMITTED')=(commit_id IS NOT NULL))
    )""")
    op.execute("CREATE INDEX ix_dag_cleanup ON dag_runs(cleaned_at)")
    op.execute("""
    CREATE TABLE dag_nodes (
      tenant_id uuid NOT NULL, job_id uuid NOT NULL, node_id varchar(80) NOT NULL,
      state varchar(20) NOT NULL, attempt integer NOT NULL, token uuid,
      started_at timestamptz, completed_at timestamptz, result_id uuid, result jsonb NOT NULL,
      error varchar(100), PRIMARY KEY(tenant_id,job_id,node_id),
      FOREIGN KEY(tenant_id,job_id) REFERENCES dag_runs(tenant_id,job_id),
      CONSTRAINT ck_dag_node_state CHECK (state IN ('PENDING','RUNNING','COMPLETED','FAILED')),
      CONSTRAINT ck_dag_node_attempt CHECK (attempt >= 0)
    )""")
    op.execute("""
    CREATE TABLE dag_outputs (
      tenant_id uuid NOT NULL, job_id uuid NOT NULL, output_id varchar(80) NOT NULL,
      dataset_id uuid NOT NULL, version_id uuid NOT NULL, state varchar(20) NOT NULL,
      result jsonb NOT NULL, PRIMARY KEY(tenant_id,job_id,output_id),
      FOREIGN KEY(tenant_id,job_id) REFERENCES dag_runs(tenant_id,job_id),
      CONSTRAINT uq_dag_output_version UNIQUE(tenant_id,dataset_id,version_id),
      CONSTRAINT uq_dag_output_target UNIQUE(tenant_id,job_id,dataset_id),
      CONSTRAINT ck_dag_output_state CHECK (state IN ('PENDING','PREPARED','COMMITTED'))
    )""")
    op.execute("""CREATE FUNCTION guard_dag_record() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE j execution_jobs; BEGIN
      IF TG_OP='DELETE' THEN
        RAISE EXCEPTION 'DAG history is retained' USING ERRCODE='23514';
      END IF;
      SELECT * INTO j FROM execution_jobs WHERE tenant_id=NEW.tenant_id AND id=NEW.job_id;
      IF j.kind <> 'PIPELINE' OR j.request->>'format_version' IS DISTINCT FROM '2' THEN
        RAISE EXCEPTION 'DAG requires pinned parent' USING ERRCODE='23514';
      END IF;
      IF TG_OP='INSERT' THEN
        IF j.state <> 'QUEUED' THEN
          RAISE EXCEPTION 'Manifest fixed at admission' USING ERRCODE='23514';
        END IF;
      ELSE
        IF OLD.tenant_id IS DISTINCT FROM NEW.tenant_id OR OLD.job_id IS DISTINCT FROM
        NEW.job_id THEN
          RAISE EXCEPTION 'Immutable DAG identity' USING ERRCODE='23514';
        END IF;
        IF TG_TABLE_NAME='dag_runs' AND j.state IN ('SUCCEEDED','FAILED','CANCELLED') THEN
          IF (to_jsonb(OLD)-'cleaned_at'-'state') IS NOT DISTINCT FROM
             (to_jsonb(NEW)-'cleaned_at'-'state') AND
             (OLD.state=NEW.state OR (j.state IN ('FAILED','CANCELLED') AND NEW.state='ABANDONED'))
             AND NEW.cleaned_at IS NOT NULL AND
             (OLD.cleaned_at IS NULL OR NEW.cleaned_at >= OLD.cleaned_at) THEN
            RETURN NEW;
          END IF;
        END IF;
        IF j.state <> 'RUNNING' OR j.lease_until <= clock_timestamp() OR
          j.token::text IS DISTINCT FROM current_setting('foundry.execution_token',true) THEN
          RAISE EXCEPTION 'DAG requires live fence' USING ERRCODE='23514';
        END IF;
        IF TG_TABLE_NAME='dag_runs' THEN
          IF OLD.execution_started_at IS NOT NULL AND NEW.execution_started_at IS DISTINCT FROM
             OLD.execution_started_at THEN
            RAISE EXCEPTION 'DAG execution deadline is immutable' USING ERRCODE='23514';
          END IF;
          IF (OLD.plan,OLD.plan_digest) IS DISTINCT FROM (NEW.plan,NEW.plan_digest) OR
        OLD.state='COMMITTED' THEN
            RAISE EXCEPTION 'Immutable execution plan/commit' USING ERRCODE='23514';
          END IF;
        ELSIF TG_TABLE_NAME='dag_outputs' THEN
          IF (OLD.output_id,OLD.dataset_id,OLD.version_id) IS DISTINCT FROM
             (NEW.output_id,NEW.dataset_id,NEW.version_id) OR OLD.state='COMMITTED' THEN
            RAISE EXCEPTION 'Immutable output reservation' USING ERRCODE='23514';
          END IF;
        ELSIF TG_TABLE_NAME='dag_nodes' AND OLD.node_id IS DISTINCT FROM NEW.node_id THEN
          RAISE EXCEPTION 'Immutable node identity' USING ERRCODE='23514';
        END IF;
      END IF;
      RETURN NEW;
    END $$""")
    for table in ("dag_runs", "dag_nodes", "dag_outputs"):
        op.execute(
            f"CREATE TRIGGER guard_dag_record BEFORE INSERT OR UPDATE OR DELETE "
            f"ON {table} FOR EACH ROW EXECUTE FUNCTION guard_dag_record()"
        )
    op.execute("""CREATE FUNCTION guard_dag_success() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.state='SUCCEEDED' AND NEW.kind='PIPELINE' AND
        NEW.request->>'format_version'='2' THEN
        IF NOT EXISTS (SELECT 1 FROM dag_runs WHERE tenant_id=NEW.tenant_id AND job_id=NEW.id
        AND state='COMMITTED') OR
           EXISTS (SELECT 1 FROM dag_outputs o LEFT JOIN dataset_versions d ON
             (d.tenant_id,d.artifact_id,d.id)=(o.tenant_id,o.dataset_id,o.version_id)
             LEFT JOIN artifact_versions a ON
        (a.tenant_id,a.artifact_id,a.id)=(o.tenant_id,o.dataset_id,o.version_id)
             WHERE o.tenant_id=NEW.tenant_id AND o.job_id=NEW.id AND
             (o.state<>'COMMITTED' OR d.state IS DISTINCT FROM 'COMMITTED' OR a.state IS
        DISTINCT FROM 'COMMITTED')) THEN
          RAISE EXCEPTION 'Success requires all committed outputs' USING ERRCODE='23514';
        END IF;
      END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER guard_dag_success BEFORE UPDATE ON execution_jobs "
        "FOR EACH ROW EXECUTE FUNCTION guard_dag_success()"
    )
    op.execute("""CREATE OR REPLACE FUNCTION require_execution_publication(t uuid, r uuid, v uuid)
    RETURNS void LANGUAGE plpgsql AS $$ BEGIN
      IF (EXISTS (SELECT 1 FROM execution_jobs WHERE tenant_id=t AND output_dataset_id=r AND
        output_version_id=v)
          OR EXISTS (SELECT 1 FROM dag_outputs WHERE tenant_id=t AND dataset_id=r AND version_id=v))
        AND NOT EXISTS (SELECT 1 FROM execution_jobs j WHERE j.tenant_id=t AND j.state='RUNNING'
          AND j.lease_until > clock_timestamp() AND
        j.token::text=current_setting('foundry.execution_token',true)
          AND ((j.output_dataset_id=r AND j.output_version_id=v) OR EXISTS
            (SELECT 1 FROM dag_outputs o WHERE o.tenant_id=t AND o.job_id=j.id AND
        o.dataset_id=r AND o.version_id=v))) THEN
        RAISE EXCEPTION 'Output requires live fenced publication' USING ERRCODE='23514';
      END IF;
    END $$""")

    op.execute("""CREATE FUNCTION require_atomic_dag_visibility() RETURNS trigger
    LANGUAGE plpgsql AS $$ BEGIN
      IF EXISTS (SELECT 1 FROM dag_outputs o JOIN execution_jobs j ON
          (j.tenant_id,j.id)=(o.tenant_id,o.job_id)
          JOIN dag_runs r ON (r.tenant_id,r.job_id)=(o.tenant_id,o.job_id)
          WHERE (o.tenant_id,o.dataset_id,o.version_id)=
                (NEW.tenant_id,NEW.artifact_id,NEW.id)
          AND (o.state <> 'COMMITTED' OR j.state <> 'SUCCEEDED' OR r.state <> 'COMMITTED')) THEN
        RAISE EXCEPTION 'DAG visibility requires atomic parent commit' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$""")
    for table in ("artifact_versions", "dataset_versions"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER require_atomic_dag_visibility "
            f"AFTER INSERT OR UPDATE ON {table} DEFERRABLE INITIALLY DEFERRED "
            "FOR EACH ROW WHEN (NEW.state='COMMITTED') "
            "EXECUTE FUNCTION require_atomic_dag_visibility()"
        )


def downgrade() -> None:
    raise RuntimeError("DAG execution history is forward-only; restore a verified backup")
