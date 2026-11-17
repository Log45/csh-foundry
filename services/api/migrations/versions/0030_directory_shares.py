"""Pending directory share claims, preserving existing principal and tenant invitations."""

from alembic import op

revision = "0030_directory_shares"
down_revision = "0029_personal_tenants"
branch_labels = None
depends_on = None

RECIPIENT = """num_nonnulls(recipient_principal_id, recipient_tenant_id, directory_digest) = 1
AND (directory_digest IS NULL OR state IN ('pending', 'revoked'))
AND num_nonnulls(directory_username, directory_issuer, directory_sender_subject,
    directory_digest, directory_expires_at) IN (0, 5)"""


def upgrade() -> None:
    op.execute("""
        ALTER TABLE tenant_shares
            ADD COLUMN directory_username varchar(200),
            ADD COLUMN directory_issuer varchar(2048),
            ADD COLUMN directory_sender_subject varchar(512),
            ADD COLUMN directory_digest varchar(64),
            ADD COLUMN directory_expires_at timestamptz,
            DROP CONSTRAINT ck_share_recipient
    """)
    op.create_check_constraint("ck_share_recipient", "tenant_shares", RECIPIENT)


def downgrade() -> None:
    raise RuntimeError("Directory sharing migration is forward-only")
