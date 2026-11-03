"""Add Project governance without reassigning existing ontology assets.

Populated installations are forward-only. An unused installation may be rolled back.
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_projects"
down_revision = "0017_capacity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        "projects",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("state IN ('ACTIVE','ARCHIVED')", name="ck_project_state"),
        sa.CheckConstraint("revision > 0", name="ck_project_revision"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    )
    op.create_index(
        "uq_project_name",
        "projects",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("state = 'ACTIVE'"),
    )
    op.create_table(
        "project_members",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.CheckConstraint("role IN ('owner','editor','viewer')", name="ck_project_role"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "project_id", "principal_id"),
    )
    op.create_table(
        "project_folders",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("state IN ('ACTIVE','ARCHIVED')", name="ck_folder_state"),
        sa.CheckConstraint("id IS DISTINCT FROM parent_id", name="ck_folder_self"),
        sa.CheckConstraint("revision > 0", name="ck_folder_revision"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "parent_id"],
            ["project_folders.tenant_id", "project_folders.project_id", "project_folders.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "project_id", "id"),
    )
    op.create_index(
        "uq_folder_name",
        "project_folders",
        ["tenant_id", "project_id", "parent_id", "name"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text("state = 'ACTIVE'"),
    )
    op.create_table(
        "platform_resources",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("folder_id", sa.Uuid(), nullable=True),
        sa.Column("resource_type", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "resource_type IN ('ONTOLOGY_OBJECT_TYPE','ONTOLOGY_LINK_TYPE',"
            "'ONTOLOGY_ACTION','ONTOLOGY_VERSION')",
            name="ck_resource_type",
        ),
        sa.CheckConstraint("state IN ('ACTIVE','ARCHIVED')", name="ck_resource_state"),
        sa.CheckConstraint("revision > 0", name="ck_resource_revision"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "schema_version"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id", "folder_id"],
            ["project_folders.tenant_id", "project_folders.project_id", "project_folders.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "resource_type",
            "ontology_id",
            "schema_version",
            "entity_id",
            name="uq_resource_authority",
        ),
    )
    op.create_index(
        "uq_resource_name",
        "platform_resources",
        ["tenant_id", "project_id", "folder_id", "name"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text("state = 'ACTIVE'"),
    )
    op.create_table(
        "resource_shares",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "resource_id"],
            ["platform_resources.tenant_id", "platform_resources.id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "resource_id", "project_id"),
    )
    op.execute("""
        CREATE FUNCTION validate_platform_resource() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE definition jsonb; collection text;
        BEGIN
            IF TG_OP = 'UPDATE' AND
               (NEW.tenant_id, NEW.id, NEW.project_id, NEW.resource_type,
                NEW.ontology_id, NEW.schema_version, NEW.entity_id) IS DISTINCT FROM
               (OLD.tenant_id, OLD.id, OLD.project_id, OLD.resource_type,
                OLD.ontology_id, OLD.schema_version, OLD.entity_id) THEN
                RAISE EXCEPTION 'Resource authority and owning Project are immutable'
                    USING ERRCODE = '23514';
            END IF;
            SELECT definition_json::jsonb INTO definition FROM ontology_versions
            WHERE tenant_id = NEW.tenant_id AND ontology_id = NEW.ontology_id
              AND version = NEW.schema_version AND status = 'PUBLISHED';
            IF definition IS NULL THEN
                RAISE EXCEPTION 'Resource requires a published canonical version'
                    USING ERRCODE = '23514';
            END IF;
            collection := CASE NEW.resource_type
                WHEN 'ONTOLOGY_OBJECT_TYPE' THEN 'object_types'
                WHEN 'ONTOLOGY_LINK_TYPE' THEN 'link_types'
                WHEN 'ONTOLOGY_ACTION' THEN 'action_types' END;
            IF (collection IS NULL AND NEW.entity_id <> NEW.schema_version) OR
               (collection IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM jsonb_array_elements(definition -> collection) item
                    WHERE item ->> 'id' = NEW.entity_id)) THEN
                RAISE EXCEPTION 'Unknown canonical resource reference' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER validate_platform_resource BEFORE INSERT OR UPDATE ON platform_resources
        FOR EACH ROW EXECUTE FUNCTION validate_platform_resource()
    """)
    # Add permissions without changing immutable historical roles or their assignments.
    op.execute("""
        INSERT INTO security_roles (tenant_id, id, permissions)
        SELECT DISTINCT tenant_id, 'phase11-project-administrator',
          '["project:create","project:read","project:write","project:manage"]'::jsonb
        FROM role_assignments WHERE role_id = 'tenant-administrator'
        ON CONFLICT DO NOTHING
    """)
    op.execute("""
        INSERT INTO role_assignments (tenant_id, principal_id, role_id)
        SELECT tenant_id, principal_id, 'phase11-project-administrator'
        FROM role_assignments WHERE role_id = 'tenant-administrator'
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    # Legacy migration tests may roll back an unused installation. Never discard Project data.
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM projects")):
        raise RuntimeError("Populated Project governance is forward-only; restore verified backup")
    for table in (
        "resource_shares",
        "platform_resources",
        "project_folders",
        "project_members",
        "projects",
    ):
        op.drop_table(table)
    op.execute("DROP FUNCTION validate_platform_resource()")
    # Preserve immutable security role/assignment history; upgrade inserts are restart-safe.
