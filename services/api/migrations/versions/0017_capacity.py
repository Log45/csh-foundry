"""Transactional tenant artifact/history accounting and pending job admission."""

import sqlalchemy as sa
from alembic import op

revision = "0017_capacity"
down_revision = "0016_operations"
branch_labels = None
depends_on = None

TABLES = (
    "sdk_artifacts",
    "semantic_artifacts",
    "ontology_imports",
    "ontology_branch_revisions",
    "ontology_branch_merges",
    "ingestion_stage",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        "tenant_resource_usage",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("bytes_used", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("bytes_used >= 0", name="ck_usage_nonnegative"),
    )
    for table in TABLES:
        op.execute(f"""
            INSERT INTO tenant_resource_usage(tenant_id, bytes_used)
            SELECT tenant_id, sum(octet_length(to_jsonb(t)::text)) FROM {table} t GROUP BY tenant_id
            ON CONFLICT (tenant_id) DO UPDATE
            SET bytes_used = tenant_resource_usage.bytes_used + excluded.bytes_used
        """)
    op.execute("""
        CREATE FUNCTION account_tenant_artifacts() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE delta bigint; owner uuid; used bigint; capacity bigint;
        BEGIN
            IF TG_OP = 'DELETE' THEN owner := OLD.tenant_id;
            ELSE owner := NEW.tenant_id; END IF;
            delta := CASE WHEN TG_OP = 'DELETE' THEN 0 ELSE octet_length(to_jsonb(NEW)::text) END
                   - CASE WHEN TG_OP = 'INSERT' THEN 0 ELSE octet_length(to_jsonb(OLD)::text) END;
            INSERT INTO tenant_resource_usage(tenant_id, bytes_used) 
            VALUES (owner, greatest(delta, 0))
            ON CONFLICT (tenant_id) DO UPDATE
            SET bytes_used = tenant_resource_usage.bytes_used + delta
            RETURNING bytes_used INTO used;
            capacity := coalesce(nullif(current_setting('foundry.storage_limit', true), ''),
                                 '268435456')::bigint;
            IF delta > 0 AND used > capacity THEN
                RAISE EXCEPTION 'Tenant artifact capacity reached' USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END $$
    """)
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER tenant_capacity AFTER INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION account_tenant_artifacts()"
        )
    op.execute("""
        CREATE FUNCTION admit_tenant_job() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE queued bigint; capacity bigint;
        BEGIN
            IF NEW.status NOT IN ('PENDING','RUNNING') THEN RETURN NEW; END IF;
            IF TG_OP = 'UPDATE' AND OLD.status IN ('PENDING','RUNNING') THEN RETURN NEW; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(NEW.tenant_id::text, 714003));
            SELECT (SELECT count(*) FROM ingestion_runs
                    WHERE tenant_id = NEW.tenant_id AND status IN ('PENDING','RUNNING'))
                 + (SELECT count(*) FROM semantic_jobs
                    WHERE tenant_id = NEW.tenant_id AND status IN ('PENDING','RUNNING'))
            INTO queued;
            capacity := coalesce(nullif(current_setting('foundry.job_limit', true), ''),
                                 '20')::bigint;
            IF queued >= capacity THEN
                RAISE EXCEPTION 'Tenant pending job capacity reached' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    for table in ("ingestion_runs", "semantic_jobs"):
        op.execute(
            f"CREATE TRIGGER job_capacity BEFORE INSERT OR UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION admit_tenant_job()"
        )


def downgrade() -> None:
    for table in ("ingestion_runs", "semantic_jobs"):
        op.execute(f"DROP TRIGGER job_capacity ON {table}")
    for table in TABLES:
        op.execute(f"DROP TRIGGER tenant_capacity ON {table}")
    op.execute("DROP FUNCTION admit_tenant_job()")
    op.execute("DROP FUNCTION account_tenant_artifacts()")
    op.drop_table("tenant_resource_usage")
