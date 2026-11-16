"""Governed first-sign-in provisioning. Identity claims come from the API verifier."""

import hashlib
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.config import Settings
from ontology_platform.db.models import (
    AuthorizationAudit,
    ExternalIdentity,
    Membership,
    PersonalTenant,
    PlatformPrincipal,
    Role,
    RoleAssignment,
    SecurityState,
    Tenant,
)
from ontology_platform.security.audit import persist_audit
from ontology_platform.security.contracts import DEFAULT_ROLES
from ontology_platform.security.identity import lock_binding
from ontology_platform.security.job_grants import EXECUTION, INGESTION, SEMANTIC
from ontology_platform.security.oidc import Provider
from ontology_platform.security.service import denied


class OnboardingResult(BaseModel):
    personal_tenant_id: UUID | None = None


PERSONAL_WORKER = INGESTION | SEMANTIC | EXECUTION | {"worker:delegate", "execution:claim"}


def provision_worker(s: Session, settings: Settings, tenant: UUID) -> None:
    if not settings.worker_subject:
        return
    provider = next(p for p in settings.oidc_providers if p.id == settings.worker_provider_id)
    key = (provider.issuer, settings.worker_subject)
    lock_binding(s, *key)
    binding = s.get(ExternalIdentity, key)
    worker: PlatformPrincipal | None
    if binding is None:
        worker = PlatformPrincipal(id=str(uuid4()), principal_type="service", enabled=True)
        s.add(worker)
        s.flush()
        s.add(ExternalIdentity(issuer=key[0], subject=key[1], principal_id=worker.id))
    else:
        worker = s.get(PlatformPrincipal, binding.principal_id, with_for_update={"read": True})
        if worker is None or worker.principal_type != "service":
            raise denied()
    s.add(Membership(tenant_id=tenant, principal_id=worker.id, enabled=True, attributes={}))
    s.add(Role(tenant_id=tenant, id="personal-worker", permissions=sorted(PERSONAL_WORKER)))
    s.flush()
    s.add(RoleAssignment(tenant_id=tenant, principal_id=worker.id, role_id="personal-worker"))


def onboard(
    sessions: sessionmaker[Session],
    settings: Settings,
    provider: Provider,
    claims: dict[str, Any],
) -> OnboardingResult:
    subject = claims["sub"]
    client = claims.get("azp", claims.get("client_id"))
    if client == settings.worker_client_id or (
        settings.worker_subject == subject and settings.worker_provider_id == provider.id
    ):
        raise denied()
    signed_access = claims.get("realm_access")
    roles = signed_access.get("roles") if isinstance(signed_access, dict) else None
    eligible = (
        provider.personal_tenant_client == client
        and provider.personal_tenant_role is not None
        and isinstance(roles, list)
        and provider.personal_tenant_role in roles
    )
    with sessions.begin() as s:
        lock_binding(s, provider.issuer, subject)
        binding = s.get(ExternalIdentity, (provider.issuer, subject))
        principal = None
        if binding is not None:
            principal = s.get(PlatformPrincipal, binding.principal_id, with_for_update=True)
            if principal is None or not principal.enabled or principal.principal_type != "user":
                raise denied()
        if not eligible:
            if principal is None:
                raise denied()
            return OnboardingResult()
        if principal is None:
            principal = PlatformPrincipal(id=str(uuid4()), principal_type="user", enabled=True)
            s.add(principal)
            s.flush()
            s.add(
                ExternalIdentity(issuer=provider.issuer, subject=subject, principal_id=principal.id)
            )
        personal = s.get(PersonalTenant, principal.id)
        if personal is not None:
            member = s.get(Membership, (personal.tenant_id, principal.id))
            if member is None or not member.enabled:
                raise denied()
            return OnboardingResult(personal_tenant_id=personal.tenant_id)

        tenant = uuid4()
        s.add(Tenant(id=tenant, name="Personal workspace"))
        s.flush()
        s.add(SecurityState(tenant_id=tenant))
        s.flush()
        s.add(Membership(tenant_id=tenant, principal_id=principal.id, enabled=True, attributes={}))
        for role, permissions in DEFAULT_ROLES.items():
            s.add(Role(tenant_id=tenant, id=role, permissions=list(permissions)))
        s.flush()
        s.add(PersonalTenant(principal_id=principal.id, tenant_id=tenant))
        s.add(RoleAssignment(tenant_id=tenant, principal_id=principal.id, role_id="tenant-owner"))
        provision_worker(s, settings, tenant)
        persist_audit(
            s,
            [
                AuthorizationAudit(
                    id=uuid4(),
                    tenant_id=tenant,
                    principal_id=principal.id,
                    operation="tenant:onboard:committed",
                    resource_hash=hashlib.sha256(str(tenant).encode()).hexdigest(),
                    allowed=True,
                    category="administration",
                    policy_version=1,
                )
            ],
        )
        return OnboardingResult(personal_tenant_id=tenant)
