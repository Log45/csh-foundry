"""External identity lookup; membership is platform state, never a token tenant claim."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.db.models import ExternalIdentity, Membership, PlatformPrincipal
from ontology_platform.errors import ApplicationError
from ontology_platform.security.interfaces import Principal


def resolve(
    sessions: sessionmaker[Session],
    issuer: str,
    subject: str,
    tenant: UUID | None,
    *,
    method: str,
    expires_at: datetime,
) -> Principal:
    with sessions() as session:
        binding = session.get(ExternalIdentity, (issuer, subject))
        row = session.get(PlatformPrincipal, binding.principal_id) if binding else None
        if row is None or not row.enabled:
            raise ApplicationError(
                "identity_unavailable", "Identity must be provisioned and enabled", 403
            )
        memberships = list(
            session.scalars(
                select(Membership).where(
                    Membership.principal_id == row.id, Membership.enabled.is_(True)
                )
            )
        )
        if tenant is None:
            if len(memberships) != 1:
                raise ApplicationError(
                    "tenant_selection_required", "Select an authorized tenant with X-Tenant-ID", 403
                )
            tenant = memberships[0].tenant_id
        if not any(m.tenant_id == tenant for m in memberships):
            raise ApplicationError("forbidden", "Tenant membership is required", 403)
        return Principal(
            tenant_id=tenant,
            principal_id=row.id,
            identity_provider=issuer,
            external_subject=subject,
            authentication_method=method,
            principal_type=row.principal_type,
            expires_at=expires_at,
        )
