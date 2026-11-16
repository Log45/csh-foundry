"""Personal tenant ownership, cross-tenant invitations and worker dispatch indexes."""

from alembic import op

revision = "0029_personal_tenants"
down_revision = "0028_job_execution_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE personal_tenants (
            principal_id varchar(200) PRIMARY KEY,
            tenant_id uuid NOT NULL UNIQUE,
            FOREIGN KEY (tenant_id, principal_id)
                REFERENCES tenant_memberships (tenant_id, principal_id)
        )
    """)
    op.execute("""
        CREATE TABLE tenant_shares (
            id uuid PRIMARY KEY,
            owner_tenant_id uuid NOT NULL REFERENCES tenants(id),
            project_id uuid,
            ontology_id text,
            recipient_principal_id varchar(200) REFERENCES principals(id),
            recipient_tenant_id uuid REFERENCES tenants(id),
            access varchar(20) NOT NULL,
            state varchar(10) NOT NULL,
            created_by varchar(200) NOT NULL REFERENCES principals(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (owner_tenant_id, project_id) REFERENCES projects (tenant_id, id),
            FOREIGN KEY (owner_tenant_id, ontology_id) REFERENCES ontologies (tenant_id, id),
            CONSTRAINT ck_share_target CHECK (num_nonnulls(project_id, ontology_id) = 1),
            CONSTRAINT ck_share_recipient CHECK
                (num_nonnulls(recipient_principal_id, recipient_tenant_id) = 1),
            CONSTRAINT ck_share_cross_tenant CHECK (owner_tenant_id <> recipient_tenant_id),
            CONSTRAINT ck_share_state CHECK (state IN ('pending','accepted','revoked')),
            CONSTRAINT ck_share_access CHECK (access IN ('viewer','collaborator'))
        )
    """)
    op.execute("ALTER TABLE authorization_audit ADD COLUMN acting_tenant_id uuid")
    op.execute("ALTER TABLE authorization_audit ADD COLUMN share_id uuid")
    for suffix, column in (
        ("owner", "owner_tenant_id"),
        ("principal", "recipient_principal_id"),
        ("recipient", "recipient_tenant_id"),
    ):
        op.create_index("ix_tenant_share_" + suffix, "tenant_shares", [column, "created_at", "id"])
    for table, state, statuses in (
        ("ingestion_runs", "status", "'PENDING','RUNNING'"),
        ("semantic_jobs", "status", "'PENDING','RUNNING'"),
        ("execution_jobs", "state", "'QUEUED','ADMITTED','RUNNING','CANCELLING'"),
        ("outbox_events", "status", "'PENDING','CLAIMED'"),
    ):
        op.execute(
            f"CREATE INDEX ix_{table}_worker_scope ON {table} (tenant_id, {state}) "
            f"WHERE {state} IN ({statuses})"
        )


def downgrade() -> None:
    raise RuntimeError("Personal tenant and sharing migration is forward-only")
