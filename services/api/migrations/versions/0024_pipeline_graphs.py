"""Actor-private drafts and immutable canonical-definition authoring metadata."""

from alembic import op

revision = "0024_pipeline_graphs"
down_revision = "0023_media_functions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.execute("""CREATE TABLE pipeline_drafts (
        tenant_id UUID NOT NULL, pipeline_id UUID NOT NULL, actor_id TEXT NOT NULL,
        revision INTEGER NOT NULL, graph JSONB NOT NULL,
        PRIMARY KEY (tenant_id, pipeline_id, actor_id),
        FOREIGN KEY (tenant_id, pipeline_id) REFERENCES platform_resources (tenant_id, id),
        CONSTRAINT ck_pipeline_draft_revision CHECK (revision > 0),
        CONSTRAINT ck_pipeline_draft_bytes CHECK (octet_length(graph::text) <= 524288)
    )""")
    op.execute("""CREATE TABLE pipeline_graphs (
        tenant_id UUID NOT NULL, pipeline_id UUID NOT NULL, definition_id UUID NOT NULL,
        graph JSONB NOT NULL, semantic_digest VARCHAR(64) NOT NULL,
        PRIMARY KEY (tenant_id, pipeline_id, definition_id),
        FOREIGN KEY (tenant_id, pipeline_id, definition_id)
            REFERENCES pipeline_definitions (tenant_id, pipeline_id, id),
        CONSTRAINT ck_pipeline_graph_bytes CHECK (octet_length(graph::text) <= 524288)
    )""")
    op.execute("""CREATE FUNCTION immutable_pipeline_graph() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Published pipeline graphs are immutable'; END $$""")
    op.execute("""CREATE TRIGGER immutable_pipeline_graph BEFORE UPDATE OR DELETE ON pipeline_graphs
        FOR EACH ROW EXECUTE FUNCTION immutable_pipeline_graph()""")
    op.execute("""CREATE FUNCTION pipeline_draft_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM platform_resources r WHERE r.tenant_id=NEW.tenant_id
            AND r.id=NEW.pipeline_id AND r.resource_type='PIPELINE' AND r.state='ACTIVE') THEN
            RAISE EXCEPTION 'An active pipeline is required';
          END IF;
          IF TG_OP='UPDATE' AND (NEW.tenant_id<>OLD.tenant_id OR NEW.pipeline_id<>OLD.pipeline_id
              OR NEW.actor_id<>OLD.actor_id OR NEW.revision<>OLD.revision+1) THEN
            RAISE EXCEPTION 'Draft identity is fixed and revision must advance by one';
          END IF;
          RETURN NEW;
        END $$""")
    op.execute("""CREATE TRIGGER pipeline_draft_guard BEFORE INSERT OR UPDATE ON pipeline_drafts
        FOR EACH ROW EXECUTE FUNCTION pipeline_draft_guard()""")


def downgrade() -> None:
    raise RuntimeError("forward-only migration; restore an owned backup instead")
