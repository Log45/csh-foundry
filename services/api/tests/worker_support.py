"""Explicit service principal provisioning for OIDC execution integration tests."""

from uuid import uuid4

from ontology_platform.db.models import ProjectMember
from ontology_platform.projects.contracts import MemberChange
from ontology_platform.projects.service import ProjectService
from ontology_platform.security.admin import SecurityAdministration
from ontology_platform.security.contracts import AssignmentInput, IdentityInput
from ontology_platform.security.identity import resolve
from sqlalchemy import select


def provision_worker(svc, owner):
    admin = SecurityAdministration(svc.authorizer)
    subject = "worker-" + uuid4().hex
    key = admin.identity(
        owner,
        IdentityInput(issuer=owner.identity_provider, subject=subject, principal_type="service"),
    )
    admin.assign(owner, AssignmentInput(principal_id=key, role_id="tenant-administrator"))
    projects = ProjectService(svc.sessions, svc.authorizer)
    with svc.sessions() as s:
        keys = list(
            s.scalars(
                select(ProjectMember.project_id).where(
                    ProjectMember.tenant_id == owner.tenant_id,
                    ProjectMember.principal_id == owner.principal_id,
                    ProjectMember.role == "owner",
                )
            )
        )
    for project in keys:
        projects.member(
            owner,
            project,
            MemberChange(
                principal_id=key,
                role="editor",
                expected_revision=projects.get_project(owner, project).revision,
            ),
        )
    return resolve(
        svc.sessions,
        owner.identity_provider,
        subject,
        owner.tenant_id,
        method="oidc",
        expires_at=owner.expires_at,
    )
