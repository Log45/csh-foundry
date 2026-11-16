"""Cross-tenant invitations and explicit resource-scoped authorization."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Select, String, cast, or_, select
from sqlalchemy.orm import Session

from ontology_platform.db.models import (
    AuthorizationAudit,
    ExternalIdentity,
    Membership,
    Ontology,
    PlatformPrincipal,
    Project,
    ProjectMember,
    Tenant,
    TenantShare,
)
from ontology_platform.projects.service import ProjectService
from ontology_platform.security.audit import persist_audit
from ontology_platform.security.directory import DirectoryUser
from ontology_platform.security.interfaces import Principal
from ontology_platform.security.service import PlatformAuthorizer, denied

ONTOLOGY_READ = {
    "ontology:read",
    "schema:read",
    "object:read",
    "object:query",
    "object:count",
    "object:aggregate",
    "property:read",
    "link:read",
}
ONTOLOGY_EDIT = {
    "schema:write",
    "schema:validate",
    "object:create",
    "object:update",
    "property:update",
    "object:link",
    "link:create",
}
# Share context is opt-in, and routes that admit jobs or access independent Project contents
# never receive it. The authorizer separately checks the resource named by the service.
PROJECT_ROUTES = {
    "/projects/{project_id}": {"GET", "PATCH"},
    "/projects/{project_id}/folders": {"GET", "POST"},
    "/projects/{project_id}/folders/{folder_id}": {"GET", "PATCH"},
}
ONTOLOGY_ROUTES = {
    "": {"GET"},
    "/versions": {"GET", "POST"},
    "/versions/{version}": {"GET", "PUT"},
    "/versions/{version}/validate": {"POST"},
    "/object-types": {"GET"},
    "/objects/{type_id}": {"GET", "POST", "PATCH"},
    "/objects/{type_id}/{object_id}": {"GET", "PATCH"},
    "/objects/{type_id}/links/{link_id}": {"GET"},
    "/objects/{type_id}/{object_id}/links/{link_id}": {"GET"},
    "/links": {"POST"},
    "/objects/{type_id}/query": {"POST"},
    "/object-sets/query": {"POST"},
    "/traverse": {"POST"},
    "/aggregate": {"POST"},
}


PROJECT_PATH = "/api/v1"
ONTOLOGY_PATH = "/api/v1/ontologies/{ontology_id}"


def shared_route(path: str, method: str) -> Literal["project", "ontology"] | None:
    if method in PROJECT_ROUTES.get(path.removeprefix(PROJECT_PATH), set()):
        return "project"
    if path.startswith(ONTOLOGY_PATH) and method in ONTOLOGY_ROUTES.get(
        path[len(ONTOLOGY_PATH) :], set()
    ):
        return "ontology"
    return None


def describe_share_header(app: FastAPI) -> None:
    openapi = app.openapi

    def schema() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        document = openapi()
        for path, operations in document["paths"].items():
            for method, operation in operations.items():
                if shared_route(path, method.upper()):
                    operation.setdefault("parameters", []).append(
                        {
                            "name": "X-Resource-Share",
                            "in": "header",
                            "required": False,
                            "description": (
                                "Accepted resource share. X-Tenant-ID selects the acting tenant."
                            ),
                            "schema": {"type": "string", "format": "uuid"},
                        }
                    )
        return document

    app.openapi = schema  # type: ignore[method-assign]


class ShareOption(BaseModel):
    id: str
    label: str


class TenantShareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID | None = None
    ontology_id: str | None = Field(None, min_length=1, max_length=200)
    recipient_principal_id: str | None = Field(None, min_length=1, max_length=200)
    recipient_tenant_id: UUID | None = None
    access: Literal["viewer", "collaborator"]

    @model_validator(mode="after")
    def exactly_one(self) -> "TenantShareInput":
        if (self.project_id is None) == (self.ontology_id is None):
            raise ValueError("Choose one resource")
        if (self.recipient_tenant_id is None) == (self.recipient_principal_id is None):
            raise ValueError("Choose one recipient")
        return self


class TenantShareView(TenantShareInput):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    id: UUID
    owner_tenant_id: UUID
    state: Literal["pending", "accepted", "revoked"]
    created_by: str
    created_at: datetime


def share_principal(
    s: Session, p: Principal, key: UUID, method: str, path: str, params: dict[str, str]
) -> Principal:
    share = s.get(TenantShare, key)
    if share is None or share.state != "accepted":
        raise denied()
    route = shared_route(path, method)
    if share.project_id is not None:
        if route != "project" or str(share.project_id) != str(params.get("project_id", "")).lower():
            raise denied()
    elif route != "ontology" or share.ontology_id != params.get("ontology_id"):
        raise denied()
    return p.model_copy(
        update={
            "tenant_id": share.owner_tenant_id,
            "acting_tenant_id": p.tenant_id,
            "share_id": key,
        }
    )


def live_share(s: Session, p: Principal) -> TenantShare:
    share = s.get(TenantShare, p.share_id, with_for_update={"read": True}, populate_existing=True)
    if (
        share is None
        or share.state != "accepted"
        or share.owner_tenant_id != p.tenant_id
        or p.acting_tenant_id is None
        or not is_recipient(share, p.principal_id, p.acting_tenant_id)
    ):
        raise denied()
    return share


def shared_identity(s: Session, p: Principal) -> Membership:
    if p.principal_type != "user" or p.authentication_method not in {"oidc", "test"}:
        raise denied()
    if p.expires_at is None or p.expires_at <= datetime.now(UTC):
        raise denied()
    principal = s.get(
        PlatformPrincipal, p.principal_id, with_for_update={"read": True}, populate_existing=True
    )
    binding = s.get(ExternalIdentity, (p.identity_provider, p.external_subject))
    acting = s.get(
        Membership,
        (p.acting_tenant_id, p.principal_id),
        with_for_update={"read": True},
        populate_existing=True,
    )
    if (
        principal is None
        or principal.principal_type != "user"
        or not principal.enabled
        or binding is None
        or binding.principal_id != p.principal_id
        or acting is None
        or not acting.enabled
    ):
        raise denied()
    member = s.get(Membership, (p.tenant_id, p.principal_id))
    if member is not None:
        if not member.enabled:
            raise denied()
        return member
    # Only the owner's membership attributes may satisfy owner ABAC conditions.
    return Membership(
        tenant_id=p.tenant_id, principal_id=p.principal_id, enabled=True, attributes={}
    )


def share_permissions(share: TenantShare) -> set[str]:
    collaborator = share.access == "collaborator"
    if share.project_id is not None:
        return {"project:read", "project:write"} if collaborator else {"project:read"}
    return ONTOLOGY_READ | ONTOLOGY_EDIT if collaborator else set(ONTOLOGY_READ)


def protects(share: TenantShare, resource: str) -> bool:
    if share.project_id is not None:
        root = f"{share.owner_tenant_id}/projects"
        return resource in (root, f"{root}/{share.project_id}")
    root = f"{share.owner_tenant_id}/{share.ontology_id}"
    return resource == root or resource.startswith(root + "/")


def is_recipient(share: TenantShare, principal: str, tenant: UUID) -> bool:
    return share.recipient_principal_id == principal or share.recipient_tenant_id == tenant


class SharingService:
    def __init__(self, auth: PlatformAuthorizer):
        self.auth = auth

    @contextmanager
    def scope(self, p: Principal) -> Iterator[Session]:
        if p.principal_type != "user" or p.share_id is not None:
            raise denied()
        with self.auth.sessions.begin() as s, self.auth.security_context(s, p):
            self.auth.identity(s, p)
            yield s

    @staticmethod
    def owned_projects(p: Principal) -> Select[tuple[Project]]:
        return (
            select(Project)
            .join(
                ProjectMember,
                (ProjectMember.tenant_id == Project.tenant_id)
                & (ProjectMember.project_id == Project.id),
            )
            .where(
                Project.tenant_id == p.tenant_id,
                Project.state == "ACTIVE",
                ProjectMember.principal_id == p.principal_id,
                ProjectMember.role == "owner",
            )
        )

    def targets(
        self, p: Principal, target: Literal["project", "ontology"], search: str
    ) -> list[ShareOption]:
        with self.scope(p) as s:
            if target == "project":
                for permission in ("project:read", "project:manage"):
                    self.auth.require(p, permission, f"{p.tenant_id}/projects")
                projects = self.owned_projects(p).where(
                    or_(
                        Project.name.icontains(search, autoescape=True),
                        cast(Project.id, String).icontains(search, autoescape=True),
                    )
                )
                return [
                    ShareOption(id=str(row.id), label=row.name)
                    for row in s.scalars(projects.order_by(Project.name, Project.id).limit(25))
                ]
            self.auth.require(p, "security:membership:manage", f"{p.tenant_id}/security")
            self.auth.require(p, "ontology:read", f"{p.tenant_id}/ontologies")
            ontologies = select(Ontology).where(
                Ontology.tenant_id == p.tenant_id,
                Ontology.id.icontains(search, autoescape=True),
            )
            return [
                ShareOption(id=row.id, label=row.id)
                for row in s.scalars(ontologies.order_by(Ontology.id).limit(25))
            ]

    def directory_access(self, s: Session, p: Principal) -> None:
        permissions = self.auth.permissions(s, p)
        if {"security:membership:manage", "ontology:read"} <= permissions:
            return
        if {"project:read", "project:manage"} <= permissions and s.scalar(
            self.owned_projects(p).with_only_columns(Project.id).limit(1)
        ):
            return
        raise denied()

    def recipients(self, p: Principal, users: list[DirectoryUser]) -> list[ShareOption]:
        with self.scope(p) as s:
            self.directory_access(s, p)
            bindings = {
                subject: principal_id
                for subject, principal_id in s.execute(
                    select(ExternalIdentity.subject, PlatformPrincipal.id)
                    .join(PlatformPrincipal, PlatformPrincipal.id == ExternalIdentity.principal_id)
                    .where(
                        ExternalIdentity.issuer == p.identity_provider,
                        ExternalIdentity.subject.in_([user.subject for user in users]),
                        PlatformPrincipal.enabled.is_(True),
                        PlatformPrincipal.principal_type == "user",
                        PlatformPrincipal.id != p.principal_id,
                    )
                )
            }
            return [
                ShareOption(id=bindings[user.subject], label=user.label)
                for user in users
                if user.subject in bindings
            ]

    def manager(
        self, s: Session, p: Principal, share: TenantShareInput, *, revoke: bool = False
    ) -> None:
        if share.project_id is not None:
            self.auth.require(p, "project:read", f"{p.tenant_id}/projects/{share.project_id}")
            s.get(Tenant, p.tenant_id, with_for_update=True)
            if revoke:
                self.auth.require(p, "project:manage", f"{p.tenant_id}/projects/{share.project_id}")
                member = s.get(ProjectMember, (p.tenant_id, share.project_id, p.principal_id))
                if member is None or member.role != "owner":
                    raise denied()
            else:
                ProjectService(self.auth.sessions, self.auth).project(
                    s, p, share.project_id, manage=True
                )
        else:
            self.auth.require(p, "security:membership:manage", f"{p.tenant_id}/security")
            self.auth.require(p, "ontology:read", f"{p.tenant_id}/{share.ontology_id}")
            if s.get(Ontology, (p.tenant_id, share.ontology_id)) is None:
                raise denied()

    def audit(self, s: Session, p: Principal, row: TenantShare, action: str) -> None:
        persist_audit(
            s,
            [
                AuthorizationAudit(
                    id=uuid4(),
                    tenant_id=row.owner_tenant_id,
                    principal_id=p.principal_id,
                    share_id=row.id,
                    acting_tenant_id=p.tenant_id,
                    operation=f"share:{action}:committed",
                    allowed=True,
                    category="administration",
                    policy_version=0,
                    resource_hash=hashlib.sha256(f"{row.id}/{p.tenant_id}".encode()).hexdigest(),
                ),
            ],
        )

    def invite(self, p: Principal, body: TenantShareInput) -> TenantShareView:
        with self.scope(p) as s:
            self.manager(s, p, body)
            if body.recipient_principal_id is not None:
                user = s.get(PlatformPrincipal, body.recipient_principal_id)
                if (
                    user is None
                    or not user.enabled
                    or user.principal_type != "user"
                    or user.id == p.principal_id
                ):
                    raise denied()
            elif (
                body.recipient_tenant_id == p.tenant_id
                or s.get(Tenant, body.recipient_tenant_id) is None
            ):
                raise denied()
            row = TenantShare(
                id=uuid4(),
                owner_tenant_id=p.tenant_id,
                **body.model_dump(),
                state="pending",
                created_by=p.principal_id,
            )
            s.add(row)
            s.flush()
            self.audit(s, p, row, "invite")
            return TenantShareView.model_validate(row)

    def list(
        self, p: Principal, direction: Literal["incoming", "outgoing"], limit: int, offset: int
    ) -> list[TenantShareView]:
        with self.scope(p) as s:
            if direction == "incoming":
                clause = or_(
                    TenantShare.recipient_principal_id == p.principal_id,
                    TenantShare.recipient_tenant_id == p.tenant_id,
                )
            else:
                can_manage_tenant = "security:membership:manage" in self.auth.permissions(s, p)
                managed_project = (
                    select(ProjectMember.project_id)
                    .where(
                        ProjectMember.tenant_id == p.tenant_id,
                        ProjectMember.project_id == TenantShare.project_id,
                        ProjectMember.principal_id == p.principal_id,
                        ProjectMember.role == "owner",
                    )
                    .exists()
                )
                permissions = self.auth.permissions(s, p)
                clause = (TenantShare.owner_tenant_id == p.tenant_id) & or_(
                    (
                        TenantShare.ontology_id.is_not(None)
                        & can_manage_tenant
                        & ("ontology:read" in permissions)
                    ),
                    (managed_project & ({"project:read", "project:manage"} <= permissions)),
                )
            rows = s.scalars(
                select(TenantShare)
                .where(clause)
                .order_by(TenantShare.created_at.desc(), TenantShare.id)
                .limit(limit)
                .offset(offset)
            )
            return [TenantShareView.model_validate(row) for row in rows]

    def transition(self, p: Principal, key: UUID, accept: bool) -> TenantShareView:
        with self.scope(p) as s:
            row = s.get(TenantShare, key, with_for_update=True)
            if row is None:
                raise denied()
            if accept:
                if not is_recipient(row, p.principal_id, p.tenant_id):
                    raise denied()
                if row.recipient_tenant_id is not None:
                    self.auth.require(p, "security:membership:manage", f"{p.tenant_id}/security")
            else:
                if row.owner_tenant_id != p.tenant_id:
                    raise denied()
                self.manager(s, p, TenantShareView.model_validate(row), revoke=True)
            if accept and row.state == "revoked":
                raise denied()
            state = "accepted" if accept else "revoked"
            if row.state != state:
                row.state = state
                self.audit(s, p, row, "accept" if accept else "revoke")
            return TenantShareView.model_validate(row)
