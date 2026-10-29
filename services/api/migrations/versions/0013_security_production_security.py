"""production_security"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_security"
down_revision = "0012_ontology_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        "authorization_audit",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("operation", sa.String(length=200), nullable=False),
        sa.Column("resource_hash", sa.String(length=64), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("policy_version", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_authorization_audit_tenant_id"), "authorization_audit", ["tenant_id"], unique=False
    )
    op.create_table(
        "principals",
        sa.Column("id", sa.String(length=200), nullable=False),
        sa.Column("principal_type", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.CheckConstraint("principal_type IN ('user', 'service')", name="ck_principal_type"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "external_identities",
        sa.Column("issuer", sa.String(length=2048), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("principal_id", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["principals.id"],
        ),
        sa.PrimaryKeyConstraint("issuer", "subject"),
    )
    op.create_table(
        "security_state",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.BigInteger(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.create_table(
        "security_policy_versions",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_security_policy_version"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["security_state.tenant_id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", "version"),
    )
    op.create_table(
        "security_roles",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.String(length=200), nullable=False),
        sa.Column("permissions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["security_state.tenant_id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    )
    op.create_table(
        "tenant_memberships",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.String(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["principal_id"],
            ["principals.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["security_state.tenant_id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "principal_id"),
    )
    op.create_table(
        "role_assignments",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.String(length=200), nullable=False),
        sa.Column("role_id", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "principal_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.principal_id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["security_roles.tenant_id", "security_roles.id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "principal_id", "role_id"),
    )
    op.create_table(
        "security_policy_bindings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "id", "version"],
            [
                "security_policy_versions.tenant_id",
                "security_policy_versions.id",
                "security_policy_versions.version",
            ],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    )
    op.create_table(
        "worker_delegations",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("worker_id", sa.String(length=200), nullable=False),
        sa.Column("principal_id", sa.String(length=200), nullable=False),
        sa.Column("ontology_id", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.CheckConstraint("kind IN ('ingestion', 'semantic')", name="ck_delegation_kind"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "principal_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.principal_id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "worker_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.principal_id"],
        ),
        sa.PrimaryKeyConstraint("tenant_id", "worker_id", "principal_id", "ontology_id", "kind"),
    )
    # ### end Alembic commands ###

    op.execute("INSERT INTO security_state (tenant_id) SELECT id FROM tenants")
    op.execute("""
        CREATE FUNCTION security_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Security history and identity bindings are immutable'; END $$
    """)
    for table in (
        "authorization_audit",
        "external_identities",
        "security_roles",
        "security_policy_versions",
    ):
        op.execute(
            f"CREATE TRIGGER immutable_security BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION security_immutable()"
        )
    op.execute("""
        CREATE FUNCTION security_revision() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' AND NEW.tenant_id <> OLD.tenant_id THEN
            RAISE EXCEPTION 'Security tenant identity is immutable';
          END IF;
          IF TG_OP = 'DELETE' THEN
            UPDATE security_state SET revision = revision + 1 WHERE tenant_id = OLD.tenant_id;
            RETURN OLD;
          END IF;
          UPDATE security_state SET revision = revision + 1 WHERE tenant_id = NEW.tenant_id;
          RETURN NEW;
        END $$
    """)
    for table in (
        "tenant_memberships",
        "security_roles",
        "role_assignments",
        "security_policy_bindings",
        "worker_delegations",
    ):
        op.execute(
            f"CREATE TRIGGER bump_security BEFORE INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION security_revision()"
        )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("worker_delegations")
    op.drop_table("security_policy_bindings")
    op.drop_table("role_assignments")
    op.drop_table("tenant_memberships")
    op.drop_table("security_roles")
    op.drop_table("security_policy_versions")
    op.drop_table("security_state")
    op.drop_table("external_identities")
    op.drop_table("principals")
    op.drop_index(op.f("ix_authorization_audit_tenant_id"), table_name="authorization_audit")
    op.drop_table("authorization_audit")
    # ### end Alembic commands ###

    op.execute("DROP FUNCTION security_revision()")
    op.execute("DROP FUNCTION security_immutable()")
