"""Recoverable lineage, transactional invalidation, freshness and safe events. Forward-only."""

from alembic import op

revision = "0027_lineage_observability"
down_revision = "0026_pipeline_dag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.execute(
        """
CREATE TABLE lineage_edges (
  tenant_id UUID NOT NULL, 
  id VARCHAR(64) NOT NULL, 
  origin_id UUID NOT NULL, 
  source_resource_id UUID NOT NULL, 
  target_resource_id UUID NOT NULL, 
  source_key VARCHAR(500) NOT NULL, 
  target_key VARCHAR(500) NOT NULL, 
  source JSONB NOT NULL, 
  target JSONB NOT NULL, 
  relation VARCHAR(40) NOT NULL, 
  mode VARCHAR(20) NOT NULL, 
  certainty VARCHAR(30) NOT NULL, 
  provenance VARCHAR(80) NOT NULL, 
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
  PRIMARY KEY (tenant_id, id), 
  FOREIGN KEY(tenant_id, origin_id) REFERENCES platform_resources (tenant_id, id), 
  FOREIGN KEY(tenant_id, source_resource_id) REFERENCES platform_resources (tenant_id, id), 
  FOREIGN KEY(tenant_id, target_resource_id) REFERENCES platform_resources (tenant_id, id), 
  CONSTRAINT ck_lineage_mode CHECK (mode IN ('DESIGN','EXECUTION'))
)

"""
    )
    op.execute("CREATE INDEX ix_lineage_source ON lineage_edges (tenant_id, source_key, id)")
    op.execute("CREATE INDEX ix_lineage_target ON lineage_edges (tenant_id, target_key, id)")
    op.execute(
        """
CREATE TABLE lineage_pending (
  tenant_id UUID NOT NULL, 
  resource_id UUID NOT NULL, 
  generation BIGINT NOT NULL, 
  indexed_generation BIGINT NOT NULL, 
  cursor VARCHAR(500) NOT NULL, 
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
  PRIMARY KEY (tenant_id, resource_id), 
  FOREIGN KEY(tenant_id, resource_id) REFERENCES platform_resources (tenant_id, id)
)

"""
    )
    op.execute(
        """
CREATE TABLE freshness_policies (
  tenant_id UUID NOT NULL, 
  resource_id UUID NOT NULL, 
  enabled BOOLEAN NOT NULL, 
  expected_interval_seconds INTEGER, 
  max_age_seconds INTEGER, 
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
  PRIMARY KEY (tenant_id, resource_id), 
  FOREIGN KEY(tenant_id, resource_id) REFERENCES platform_resources (tenant_id, id), 
  CONSTRAINT ck_freshness_bounds CHECK ((expected_interval_seconds IS NULL OR
    expected_interval_seconds BETWEEN 60 AND 31536000) AND
    (max_age_seconds IS NULL OR max_age_seconds BETWEEN 60 AND 31536000))
)

"""
    )
    op.execute(
        """
CREATE TABLE operational_events (
  tenant_id UUID NOT NULL, 
  id UUID NOT NULL, 
  resource_id UUID NOT NULL, 
  execution_id UUID NOT NULL, 
  event_type VARCHAR(40) NOT NULL, 
  severity VARCHAR(10) NOT NULL, 
  state VARCHAR(20) NOT NULL, 
  attempt INTEGER NOT NULL, 
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
  PRIMARY KEY (tenant_id, id), 
  FOREIGN KEY(tenant_id, resource_id) REFERENCES platform_resources (tenant_id, id), 
  FOREIGN KEY(tenant_id, execution_id) REFERENCES execution_jobs (tenant_id, id)
)

"""
    )
    op.execute(
        "CREATE INDEX ix_operational_events_page "
        "ON operational_events (tenant_id, resource_id, created_at, id)"
    )
    op.execute("""CREATE FUNCTION enqueue_lineage() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE rid uuid;
    BEGIN
      rid := (to_jsonb(NEW)->>TG_ARGV[0])::uuid;
      INSERT INTO lineage_pending
      (tenant_id,resource_id,generation,indexed_generation,cursor)
      VALUES(NEW.tenant_id,rid,1,0,'')
      ON CONFLICT(tenant_id,resource_id) DO UPDATE
      SET generation=lineage_pending.generation+1,cursor='',updated_at=clock_timestamp();
      RETURN NEW;
    END $$""")
    for table, field in [
        ("platform_resources", "id"),
        ("artifact_versions", "artifact_id"),
        ("dataset_versions", "artifact_id"),
        ("pipeline_definitions", "pipeline_id"),
        ("pipeline_graphs", "pipeline_id"),
        ("execution_jobs", "resource_id"),
        ("mapping_definitions", "mapping_id"),
        ("application_versions", "application_id"),
        ("governed_definitions", "resource_id"),
    ]:
        op.execute(
            f"CREATE TRIGGER lineage_enqueue AFTER INSERT OR UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION enqueue_lineage('{field}')"
        )
    op.execute("""INSERT INTO lineage_pending
      (tenant_id,resource_id,generation,indexed_generation,cursor)
      SELECT tenant_id,id,1,0,'' FROM platform_resources""")
    op.execute("""CREATE FUNCTION lineage_edge_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'lineage index edges are append only'; END $$""")
    op.execute(
        "CREATE TRIGGER lineage_immutable BEFORE UPDATE OR DELETE ON lineage_edges "
        "FOR EACH ROW EXECUTE FUNCTION lineage_edge_immutable()"
    )
    op.execute("""CREATE FUNCTION execution_operational_event()
      RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP='INSERT' OR NEW.state IS DISTINCT FROM OLD.state
          OR NEW.attempts IS DISTINCT FROM OLD.attempts THEN
          INSERT INTO operational_events(tenant_id,id,resource_id,execution_id,event_type,
            severity,state,attempt)
          VALUES(NEW.tenant_id,gen_random_uuid(),NEW.resource_id,NEW.id,'execution.state',
            CASE WHEN NEW.state='FAILED' THEN 'ERROR' ELSE 'INFO' END,NEW.state,NEW.attempts);
        END IF;
        RETURN NEW;
      END $$""")
    op.execute(
        "CREATE TRIGGER execution_event AFTER INSERT OR UPDATE ON execution_jobs "
        "FOR EACH ROW EXECUTE FUNCTION execution_operational_event()"
    )


def downgrade() -> None:
    raise RuntimeError("forward-only migration; recover using a verified isolated restore")
