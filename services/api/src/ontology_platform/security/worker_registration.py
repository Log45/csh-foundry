"""Enroll the operator-configured worker identity for persisted tenant work."""

import hashlib
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from ontology_platform.db.models import (
    AuthorizationAudit,
    ExternalIdentity,
    Membership,
    PlatformPrincipal,
    Project,
    ProjectMember,
    Role,
    RoleAssignment,
    SecurityState,
    Tenant,
)
from ontology_platform.security.audit import persist_audit
from ontology_platform.security.identity import lock_binding
from ontology_platform.security.job_grants import EXECUTION, INGESTION, SEMANTIC
from ontology_platform.security.service import denied

WORKER_ROLE = "system-worker-v1"
WORKER_PERMISSIONS = (
    INGESTION
    | SEMANTIC
    | EXECUTION
    | {
        "worker:delegate",
        "execution:claim",
        "automation:dispatch",
        "ingestion:cleanup",
        "outbox:deliver",
    }
)


def register(s: Session, issuer: str, subject: str) -> str:
    """Called only after verifying the configured worker's client and access token."""
    lock_binding(s, issuer, subject)
    binding = s.get(ExternalIdentity, (issuer, subject))
    principal: PlatformPrincipal | None
    if binding is None:
        principal = PlatformPrincipal(id=str(uuid4()), principal_type="service", enabled=True)
        s.add(principal)
        s.flush()
        s.add(ExternalIdentity(issuer=issuer, subject=subject, principal_id=principal.id))
        s.flush()
    else:
        principal = s.get(PlatformPrincipal, binding.principal_id, with_for_update=True)
        if principal is None or not principal.enabled or principal.principal_type != "service":
            raise denied()
    return principal.id


def enroll(s: Session, tenant: UUID, principal: str, projects: set[UUID]) -> None:
    """Serialize with tenant administration and retain explicit disabled/viewer restrictions."""
    state = s.get(SecurityState, tenant, with_for_update=True)
    if state is None:
        return
    s.get(Tenant, tenant, with_for_update=True)
    changes = []
    member = s.get(Membership, (tenant, principal))
    if member is None:
        role = s.get(Role, (tenant, WORKER_ROLE))
        if role is None:
            s.add(Role(tenant_id=tenant, id=WORKER_ROLE, permissions=sorted(WORKER_PERMISSIONS)))
        elif set(role.permissions) != WORKER_PERMISSIONS:
            raise denied()
        s.add(Membership(tenant_id=tenant, principal_id=principal, enabled=True, attributes={}))
        s.flush()
        s.add(RoleAssignment(tenant_id=tenant, principal_id=principal, role_id=WORKER_ROLE))
        changes.append("tenant")
    elif not member.enabled:
        return
    for project_id in sorted(projects):
        project = s.get(Project, (tenant, project_id))
        if project is None or project.state != "ACTIVE":
            continue
        if s.get(ProjectMember, (tenant, project_id, principal)) is None:
            s.add(
                ProjectMember(
                    tenant_id=tenant,
                    project_id=project_id,
                    principal_id=principal,
                    role="editor",
                )
            )
            changes.append(str(project_id))
    if changes:
        s.flush()
        s.refresh(state)
        persist_audit(
            s,
            [
                AuthorizationAudit(
                    id=uuid4(),
                    tenant_id=tenant,
                    principal_id=principal,
                    actor_id=principal,
                    operation="worker:auto_enroll:committed",
                    resource_hash=hashlib.sha256("|".join(changes).encode()).hexdigest(),
                    allowed=True,
                    category="administration",
                    policy_version=state.revision,
                )
            ],
        )
