"""Private published-schema SDK artifacts. Downgrade removes generated artifacts only."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015_sdk"
down_revision = "0014_branches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        "sdk_artifacts",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("schema_status", sa.String(20), nullable=False),
        sa.Column("language", sa.String(20), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("files_json", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("tenant_id", "ontology_id", "id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "schema_version", "schema_status"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
                "ontology_versions.status",
            ],
        ),
        sa.UniqueConstraint("tenant_id", "ontology_id", "content_hash", name="uq_sdk_content"),
        sa.CheckConstraint("schema_status = 'PUBLISHED'", name="ck_sdk_published"),
        sa.CheckConstraint("language IN ('python','typescript')", name="ck_sdk_language"),
        sa.CheckConstraint("octet_length(files_json) <= 8388608", name="ck_sdk_size"),
    )
    op.execute(
        "CREATE TRIGGER sdk_immutable BEFORE UPDATE OR DELETE ON sdk_artifacts "
        "FOR EACH ROW EXECUTE FUNCTION protect_branch_history()"
    )


def downgrade() -> None:
    op.drop_table("sdk_artifacts")
