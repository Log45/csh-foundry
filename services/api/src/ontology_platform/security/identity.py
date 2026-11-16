"""External identity lookup; membership is platform state, never a token tenant claim."""

import hashlib
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.db.models import ExternalIdentity, Membership, PlatformPrincipal
from ontology_platform.errors import ApplicationError
from ontology_platform.security.interfaces import Principal


def lock_binding(session: Session, issuer: str, subject: str) -> None:
    digest = hashlib.sha256((issuer + "\0" + subject).encode()).digest()
    session.execute(
        select(func.pg_advisory_xact_lock(int.from_bytes(digest[:8], "big", signed=True)))
    )


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
        memberships = select(Membership.tenant_id).where(
            Membership.principal_id == row.id, Membership.enabled.is_(True)
        )
        if tenant is None:
            eligible = session.scalars(memberships.limit(2)).all()
            if len(eligible) != 1:
                raise ApplicationError(
                    "tenant_selection_required", "Select an authorized tenant with X-Tenant-ID", 403
                )
            tenant = eligible[0]
        elif session.scalar(memberships.where(Membership.tenant_id == tenant)) is None:
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


def own_tenants(
    sessions: sessionmaker[Session], issuer: str, subject: str, limit: int = 100, offset: int = 0
) -> list[dict[str, str]]:
    """Identity-scoped membership discovery; never grants tenant authority."""
    from ontology_platform.db.models import PersonalTenant, Tenant

    with sessions.begin() as session:
        binding = session.get(ExternalIdentity, (issuer, subject))
        row = session.get(PlatformPrincipal, binding.principal_id) if binding else None
        if row is None or not row.enabled:
            raise ApplicationError("forbidden", "Identity is unavailable", 403)
        return [
            {"id": str(tenant.id), "name": tenant.name}
            for tenant in session.scalars(
                select(Tenant)
                .join(Membership, Membership.tenant_id == Tenant.id)
                .outerjoin(
                    PersonalTenant,
                    (PersonalTenant.tenant_id == Tenant.id)
                    & (PersonalTenant.principal_id == row.id),
                )
                .where(Membership.principal_id == row.id, Membership.enabled.is_(True))
                .order_by(PersonalTenant.tenant_id.is_(None), Tenant.id)
                .limit(limit)
                .offset(offset)
            )
        ]
