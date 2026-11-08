"""Dynamic job-scoped service execution authority. Forward-only; no legacy backfill."""

from alembic import op

revision = "0028_job_execution_grants"
down_revision = "0027_lineage_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.execute("""
CREATE TABLE job_execution_grants (
	id UUID NOT NULL, 
	tenant_id UUID NOT NULL, 
	principal_id VARCHAR(200) NOT NULL, 
	ontology_id TEXT, 
	ingestion_id UUID, 
	semantic_id UUID, 
	execution_id UUID, 
	operations JSONB NOT NULL, 
	resources JSONB NOT NULL, 
	projects JSONB NOT NULL, 
	ontologies JSONB NOT NULL, 
	worker_permission VARCHAR(100) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id, principal_id) REFERENCES tenant_memberships (tenant_id, principal_id), 
	FOREIGN KEY(tenant_id, ontology_id, ingestion_id)
      REFERENCES ingestion_runs (tenant_id, ontology_id, id), 
	FOREIGN KEY(tenant_id, ontology_id, semantic_id)
      REFERENCES semantic_jobs (tenant_id, ontology_id, id), 
	FOREIGN KEY(tenant_id, execution_id) REFERENCES execution_jobs (tenant_id, id), 
	CONSTRAINT ck_job_grant_binding
      CHECK (num_nonnulls(ingestion_id, semantic_id, execution_id) = 1), 
	CONSTRAINT ck_job_grant_ontology CHECK ((execution_id IS NOT NULL) = (ontology_id IS NULL)), 
	CONSTRAINT uq_grant_ingestion UNIQUE (tenant_id, ontology_id, ingestion_id), 
	CONSTRAINT uq_grant_semantic UNIQUE (tenant_id, ontology_id, semantic_id), 
	CONSTRAINT uq_grant_execution UNIQUE (tenant_id, execution_id)
)

""")
    op.execute("ALTER TABLE authorization_audit ADD COLUMN job_id UUID")
    op.execute("ALTER TABLE authorization_audit ADD COLUMN execution_grant_id UUID")
    op.execute("ALTER TABLE authorization_audit ADD COLUMN execution_token UUID")
    op.execute("CREATE INDEX ix_audit_job ON authorization_audit (tenant_id, job_id)")
    op.execute(
        "CREATE INDEX ix_ingestion_shared_claim ON ingestion_runs "
        "(tenant_id, ontology_id, status, created_at, id)"
    )
    op.execute(
        "CREATE INDEX ix_semantic_shared_claim ON semantic_jobs "
        "(tenant_id, ontology_id, status, created_at, id)"
    )
    op.execute("""
CREATE FUNCTION guard_job_grant() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (to_jsonb(NEW) - 'revoked_at') IS DISTINCT FROM (to_jsonb(OLD) - 'revoked_at')
     OR (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at) THEN
    RAISE EXCEPTION 'Job grant binding and scope are immutable';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER guard_job_grant BEFORE UPDATE ON job_execution_grants
FOR EACH ROW EXECUTE FUNCTION guard_job_grant();
""")


def downgrade() -> None:
    raise RuntimeError("Job execution security migration is forward-only")
