"""Serialize type edits against concurrent publication at the database boundary."""

from alembic import op

revision = "0003_snapshot_locks"
down_revision = "0002_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION protect_type_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent_status text;
        BEGIN
          IF TG_OP != 'INSERT' THEN
            SELECT status INTO parent_status FROM ontology_versions WHERE tenant_id = OLD.tenant_id
              AND ontology_id = OLD.ontology_id AND version = OLD.schema_version FOR SHARE;
            IF parent_status = 'PUBLISHED' THEN
              RAISE EXCEPTION 'published type snapshots are immutable' USING ERRCODE = '23514';
            END IF;
          END IF;
          IF TG_OP != 'DELETE' THEN
            SELECT status INTO parent_status FROM ontology_versions WHERE tenant_id = NEW.tenant_id
              AND ontology_id = NEW.ontology_id AND version = NEW.schema_version FOR SHARE;
            IF parent_status = 'PUBLISHED' THEN
              RAISE EXCEPTION 'published type snapshots are immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
          END IF;
          RETURN OLD;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION protect_type_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP != 'INSERT' THEN
            PERFORM 1 FROM ontology_versions WHERE tenant_id = OLD.tenant_id
              AND ontology_id = OLD.ontology_id AND version = OLD.schema_version
              AND status = 'PUBLISHED' FOR SHARE;
            IF FOUND THEN
              RAISE EXCEPTION 'published type snapshots are immutable' USING ERRCODE = '23514';
            END IF;
          END IF;
          IF TG_OP != 'DELETE' THEN
            PERFORM 1 FROM ontology_versions WHERE tenant_id = NEW.tenant_id
              AND ontology_id = NEW.ontology_id AND version = NEW.schema_version
              AND status = 'PUBLISHED' FOR SHARE;
            IF FOUND THEN
              RAISE EXCEPTION 'published type snapshots are immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
          END IF;
          RETURN OLD;
        END $$;
    """)
