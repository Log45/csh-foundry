"""ingestion_diagnostics"""

import sqlalchemy as sa
from alembic import op

revision = "0009_ingestion_diagnostics"
down_revision = "0008_ingestion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.add_column(
        "ingestion_diagnostics", sa.Column("mapping_id", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "ingestion_diagnostics", sa.Column("mapping_version", sa.Integer(), nullable=True)
    )
    op.add_column(
        "ingestion_runs", sa.Column("staging_purged_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_ingestion_diag_mapping",
        "ingestion_diagnostics",
        "ingestion_mappings",
        ["tenant_id", "ontology_id", "mapping_id", "mapping_version"],
        ["tenant_id", "ontology_id", "id", "version"],
    )
    op.create_check_constraint(
        "ck_ingestion_policy",
        "ingestion_runs",
        "policy IN ('reject_run','reject_batch','quarantine')",
    )
    op.create_check_constraint(
        "ck_ingestion_lease",
        "ingestion_runs",
        "status != 'RUNNING' OR (token IS NOT NULL AND lease_until IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_ingestion_counts",
        "ingestion_runs",
        "created >= 0 AND updated >= 0 AND rejected >= 0 AND processed >= 0 AND links_created >= 0",
    )
    op.drop_constraint("ck_ingestion_stage_state", "ingestion_stage", type_="check")
    op.create_check_constraint(
        "ck_ingestion_stage_state",
        "ingestion_stage",
        "state IN ('STAGED','INVALID','OBJECT_DONE','DONE','REJECTED','LINK_REJECTED')",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.drop_constraint("fk_ingestion_diag_mapping", "ingestion_diagnostics", type_="foreignkey")
    for name in ("ck_ingestion_policy", "ck_ingestion_lease", "ck_ingestion_counts"):
        op.drop_constraint(name, "ingestion_runs", type_="check")
    op.execute("UPDATE ingestion_stage SET state='REJECTED' WHERE state='LINK_REJECTED'")
    op.drop_constraint("ck_ingestion_stage_state", "ingestion_stage", type_="check")
    op.create_check_constraint(
        "ck_ingestion_stage_state",
        "ingestion_stage",
        "state IN ('STAGED','INVALID','OBJECT_DONE','DONE','REJECTED')",
    )
    op.drop_column("ingestion_runs", "staging_purged_at")
    op.drop_column("ingestion_diagnostics", "mapping_version")
    op.drop_column("ingestion_diagnostics", "mapping_id")
