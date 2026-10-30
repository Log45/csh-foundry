"""Governed branches and immutable revision/merge provenance; downgrade deletes this history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014_branches"
down_revision = "0013_security"
branch_labels = None
depends_on = None


def ownership() -> list[sa.Column]:
    return [
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ontology_id", sa.Text(), nullable=False),
    ]


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        "ontology_branches",
        *ownership(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("base_version", sa.Text(), nullable=False),
        sa.Column("base_status", sa.String(20), nullable=False),
        sa.Column("base_hash", sa.String(64), nullable=False),
        sa.Column("head_revision", sa.BigInteger(), nullable=False),
        sa.Column("head_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("tenant_id", "ontology_id", "id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "base_version", "base_status"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
                "ontology_versions.status",
            ],
        ),
        sa.UniqueConstraint("tenant_id", "ontology_id", "name", name="uq_branch_name"),
        sa.CheckConstraint("base_status = 'PUBLISHED'", name="ck_branch_published_base"),
        sa.CheckConstraint("state IN ('ACTIVE','MERGED','ABANDONED')", name="ck_branch_state"),
        sa.CheckConstraint("head_revision >= 1", name="ck_branch_revision"),
    )
    op.create_table(
        "ontology_branch_revisions",
        *ownership(),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("parent_revision", sa.BigInteger()),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("definition_json", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("tenant_id", "ontology_id", "branch_id", "revision"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "branch_id"],
            [
                "ontology_branches.tenant_id",
                "ontology_branches.ontology_id",
                "ontology_branches.id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "branch_id", "parent_revision"],
            [
                "ontology_branch_revisions.tenant_id",
                "ontology_branch_revisions.ontology_id",
                "ontology_branch_revisions.branch_id",
                "ontology_branch_revisions.revision",
            ],
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "ontology_id",
            "branch_id",
            "revision",
            "content_hash",
            name="uq_branch_revision_hash",
        ),
        sa.CheckConstraint(
            "(revision = 1 AND parent_revision IS NULL) OR "
            "(revision > 1 AND parent_revision = revision - 1)",
            name="ck_branch_parent",
        ),
        sa.CheckConstraint(
            "octet_length(definition_json) <= 65536", name="ck_branch_snapshot_size"
        ),
    )
    op.create_foreign_key(
        "fk_branch_head",
        "ontology_branches",
        "ontology_branch_revisions",
        ["tenant_id", "ontology_id", "id", "head_revision", "head_hash"],
        ["tenant_id", "ontology_id", "branch_id", "revision", "content_hash"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "ontology_branch_merges",
        *ownership(),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("source_revision", sa.BigInteger(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("target_revision", sa.BigInteger(), nullable=False),
        sa.Column("result_revision", sa.BigInteger(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("tenant_id", "ontology_id", "id"),
        *(
            sa.ForeignKeyConstraint(
                ["tenant_id", "ontology_id", branch, rev],
                [
                    "ontology_branch_revisions.tenant_id",
                    "ontology_branch_revisions.ontology_id",
                    "ontology_branch_revisions.branch_id",
                    "ontology_branch_revisions.revision",
                ],
            )
            for branch, rev in (
                ("source_id", "source_revision"),
                ("target_id", "target_revision"),
                ("target_id", "result_revision"),
            )
        ),
        sa.CheckConstraint(
            "octet_length(provenance::text) <= 65536", name="ck_merge_provenance_size"
        ),
    )
    op.execute("""CREATE FUNCTION protect_branch_history() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'branch history is immutable' USING ERRCODE = '23514'; END $$""")
    for table in ("ontology_branch_revisions", "ontology_branch_merges"):
        op.execute(
            f"CREATE TRIGGER branch_history_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_branch_history()"
        )
    op.execute("""CREATE FUNCTION protect_branch() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'abandon branches instead' USING ERRCODE = '23514';
      END IF;
      IF TG_OP = 'UPDATE' AND (OLD.state != 'ACTIVE' OR
        (NEW.tenant_id,NEW.ontology_id,NEW.id,NEW.base_version,NEW.base_hash,NEW.created_by,NEW.created_at)
        IS DISTINCT FROM
        (OLD.tenant_id,OLD.ontology_id,OLD.id,OLD.base_version,OLD.base_hash,OLD.created_by,OLD.created_at)
        OR NEW.head_revision < OLD.head_revision OR NEW.head_revision > OLD.head_revision + 1) THEN
        RAISE EXCEPTION 'invalid branch transition' USING ERRCODE = '23514';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM ontology_versions WHERE tenant_id=NEW.tenant_id
        AND ontology_id=NEW.ontology_id AND version=NEW.base_version
        AND status='PUBLISHED' AND content_hash=NEW.base_hash) THEN
        RAISE EXCEPTION 'invalid immutable base' USING ERRCODE = '23514';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER branch_guard BEFORE INSERT OR UPDATE OR DELETE ON ontology_branches "
        "FOR EACH ROW EXECUTE FUNCTION protect_branch()"
    )


def downgrade() -> None:
    op.drop_table("ontology_branch_merges")
    op.drop_constraint("fk_branch_head", "ontology_branches", type_="foreignkey")
    op.drop_table("ontology_branch_revisions")
    op.drop_table("ontology_branches")
    op.execute("DROP FUNCTION protect_branch_history()")
    op.execute("DROP FUNCTION protect_branch()")
