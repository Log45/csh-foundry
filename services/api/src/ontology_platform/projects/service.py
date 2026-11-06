"""Project operations compose tenant authority with explicit collaboration membership."""

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from ontology_platform.branching.service import page
from ontology_platform.db.governance import GovernedService, missing
from ontology_platform.db.models import (
    AuthorizationAudit,
    Folder,
    Membership,
    PlatformPrincipal,
    Project,
    ProjectMember,
    Resource,
    ResourceShare,
    Role,
    RoleAssignment,
    SecurityState,
    Tenant,
)
from ontology_platform.errors import ApplicationError
from ontology_platform.projects.adapters import HANDLERS
from ontology_platform.projects.contracts import (
    CatalogImport,
    CreateFolder,
    CreateProject,
    CreateResource,
    FolderView,
    MemberChange,
    MemberView,
    ProjectView,
    ResourceView,
    ShareChange,
    ShareView,
    UpdateFolder,
    UpdateProject,
    UpdateResource,
)
from ontology_platform.security.interfaces import Principal
from ontology_platform.security.service import PlatformAuthorizer


def conflict(message: str) -> ApplicationError:
    return ApplicationError("project_conflict", message, 409)


def expected(row: Project | Folder | Resource, revision: int) -> None:
    if row.revision != revision:
        raise ApplicationError("revision_changed", "Revision changed; reload", 412)
    if row.state != "ACTIVE":
        raise conflict("Archived assets cannot be changed")


class ProjectService(GovernedService):
    @contextmanager
    def scope(self, p: Principal, permission: str = "project:read") -> Iterator[Session]:
        with self.operation(p, permission, "projects") as session:
            # One bounded lock domain also covers share revocation across Projects. Always
            # acquire after the existing security snapshot lock; no authority cache survives it.
            session.get(Tenant, p.tenant_id, with_for_update=True)
            yield session

    def project(
        self, s: Session, p: Principal, key: UUID, *, write: bool = False, manage: bool = False
    ) -> tuple[Project, ProjectMember]:
        row = s.get(Project, (p.tenant_id, key))
        member = s.get(ProjectMember, (p.tenant_id, key, p.principal_id))
        if row is None or member is None:
            if isinstance(self.authorizer, PlatformAuthorizer):
                self.authorizer.policy_denial(p, "project:read", f"{p.tenant_id}/projects/{key}")
            raise missing("Project")
        if write or manage:
            self.authorizer.require(
                p, "project:manage" if manage else "project:write", f"{p.tenant_id}/projects/{key}"
            )
            if member.role not in ({"owner"} if manage else {"owner", "editor"}):
                raise ApplicationError("forbidden", "Operation is not authorized", 403)
            if row.state != "ACTIVE":
                raise conflict("Archived Project is read-only")
        return row, member

    @staticmethod
    def project_view(row: Project, member: ProjectMember) -> ProjectView:
        return ProjectView.model_validate(
            {
                **{key: getattr(row, key) for key in ProjectView.model_fields if key != "role"},
                "role": member.role,
            }
        )

    @staticmethod
    def audit(s: Session, p: Principal, event: str, key: UUID, details: object = None) -> None:
        s.add(
            AuthorizationAudit(
                id=uuid4(),
                tenant_id=p.tenant_id,
                principal_id=p.principal_id,
                actor_id=p.actor_id,
                operation=f"project:{event}:committed",
                allowed=True,
                category="project",
                policy_version=s.scalar(
                    select(SecurityState.revision).where(SecurityState.tenant_id == p.tenant_id)
                )
                or 0,
                resource_hash=hashlib.sha256(
                    json.dumps(
                        [str(p.tenant_id), str(key), details], sort_keys=True, default=str
                    ).encode()
                ).hexdigest(),
            )
        )

    def touch(
        self,
        s: Session,
        p: Principal,
        row: Project | Folder | Resource,
        event: str,
        details: object = None,
    ) -> None:
        row.revision += 1
        row.updated_by, row.updated_at = p.principal_id, datetime.now(UTC)
        self.audit(s, p, event, row.id, details)
        s.flush()

    def create_project(self, p: Principal, body: CreateProject) -> ProjectView:
        with self.scope(p, "project:create") as s:
            for permission in ("project:read", "project:manage"):
                self.authorizer.require(p, permission, f"{p.tenant_id}/projects")
            row = Project(
                tenant_id=p.tenant_id,
                id=uuid4(),
                **body.model_dump(),
                created_by=p.principal_id,
                updated_by=p.principal_id,
            )
            s.add(row)
            s.flush()
            member = ProjectMember(
                tenant_id=p.tenant_id, project_id=row.id, principal_id=p.principal_id, role="owner"
            )
            s.add(member)
            self.audit(s, p, "create", row.id)
            s.flush()
            return self.project_view(row, member)

    def list_projects(self, p: Principal, limit: int = 50, offset: int = 0) -> list[ProjectView]:
        page(limit, offset)
        with self.scope(p) as s:
            rows = s.execute(
                select(Project, ProjectMember)
                .join(
                    ProjectMember,
                    (ProjectMember.tenant_id == Project.tenant_id)
                    & (ProjectMember.project_id == Project.id),
                )
                .where(
                    Project.tenant_id == p.tenant_id, ProjectMember.principal_id == p.principal_id
                )
                .order_by(Project.name, Project.id)
                .offset(offset)
                .limit(limit)
            )
            return [self.project_view(row, member) for row, member in rows]

    def get_project(self, p: Principal, key: UUID) -> ProjectView:
        with self.scope(p) as s:
            return self.project_view(*self.project(s, p, key))

    def update_project(
        self, p: Principal, key: UUID, body: UpdateProject | None, revision: int
    ) -> ProjectView:
        with self.scope(p) as s:
            row, member = self.project(s, p, key, manage=True)
            expected(row, revision)
            if body:
                row.name, row.description = body.name, body.description
            else:
                row.state = "ARCHIVED"
            self.touch(s, p, row, "update" if body else "archive")
            return self.project_view(row, member)

    def members(
        self, p: Principal, key: UUID, limit: int = 50, offset: int = 0
    ) -> list[MemberView]:
        page(limit, offset)
        with self.scope(p) as s:
            self.project(s, p, key)
            return [
                MemberView.model_validate(row)
                for row in s.scalars(
                    select(ProjectMember)
                    .where(ProjectMember.tenant_id == p.tenant_id, ProjectMember.project_id == key)
                    .order_by(ProjectMember.principal_id)
                    .offset(offset)
                    .limit(limit)
                )
            ]

    def member(self, p: Principal, key: UUID, body: MemberChange) -> ProjectView:
        with self.scope(p) as s:
            row, actor = self.project(s, p, key, manage=True)
            expected(row, body.expected_revision)
            old = s.get(ProjectMember, (p.tenant_id, key, body.principal_id))
            if body.role is not None:
                tenant_member = s.get(Membership, (p.tenant_id, body.principal_id))
                principal = s.get(PlatformPrincipal, body.principal_id)
                if (
                    not tenant_member
                    or not tenant_member.enabled
                    or not principal
                    or not principal.enabled
                ):
                    raise missing("Tenant member")
            if body.role == "owner" and isinstance(self.authorizer, PlatformAuthorizer):
                permissions = self.authorizer.permissions(
                    s, p.model_copy(update={"principal_id": body.principal_id})
                )
                if not {"project:read", "project:manage"} <= permissions:
                    raise conflict("An owner requires Project read and manage permissions")
            if old and old.role == "owner" and body.role != "owner":
                owners_query = (
                    select(func.count())
                    .select_from(ProjectMember)
                    .where(
                        ProjectMember.tenant_id == p.tenant_id,
                        ProjectMember.project_id == key,
                        ProjectMember.role == "owner",
                        ProjectMember.principal_id != body.principal_id,
                    )
                )
                if isinstance(self.authorizer, PlatformAuthorizer):
                    owners_query = (
                        owners_query.join(
                            Membership,
                            (Membership.tenant_id == ProjectMember.tenant_id)
                            & (Membership.principal_id == ProjectMember.principal_id),
                        )
                        .join(PlatformPrincipal, PlatformPrincipal.id == ProjectMember.principal_id)
                        .where(Membership.enabled, PlatformPrincipal.enabled)
                    )
                if isinstance(self.authorizer, PlatformAuthorizer):
                    for permission in ("project:read", "project:manage"):
                        owners_query = owners_query.where(
                            exists(
                                select(RoleAssignment.principal_id)
                                .join(
                                    Role,
                                    (Role.tenant_id == RoleAssignment.tenant_id)
                                    & (Role.id == RoleAssignment.role_id),
                                )
                                .where(
                                    RoleAssignment.tenant_id == p.tenant_id,
                                    RoleAssignment.principal_id == ProjectMember.principal_id,
                                    Role.permissions.contains([permission]),
                                )
                            )
                        )
                owners = s.scalar(owners_query)
                if owners is None or owners < 1:
                    raise conflict("Cannot remove the last owner; add another owner first")
            if body.role is None:
                if old:
                    s.delete(old)
            elif old:
                old.role = body.role
            else:
                s.add(
                    ProjectMember(
                        tenant_id=p.tenant_id,
                        project_id=key,
                        principal_id=body.principal_id,
                        role=body.role,
                    )
                )
            self.touch(s, p, row, "membership", body.model_dump(mode="json"))
            # The caller may have removed their own membership: return their previous role
            # only in this mutation response. Subsequent operations recheck membership.
            return self.project_view(row, actor)

    @staticmethod
    def folder(s: Session, p: Principal, project: UUID, key: UUID) -> Folder:
        row = s.get(Folder, (p.tenant_id, project, key))
        if row is None:
            raise missing("Folder")
        return row

    def folders(
        self,
        p: Principal,
        project: UUID,
        parent: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[FolderView]:
        page(limit, offset)
        with self.scope(p) as s:
            row, _ = self.project(s, p, project)
            if row.state != "ACTIVE":
                return []
            if parent:
                self.folder(s, p, project, parent)
            return [
                FolderView.model_validate(row)
                for row in s.scalars(
                    select(Folder)
                    .where(
                        Folder.tenant_id == p.tenant_id,
                        Folder.project_id == project,
                        Folder.parent_id == parent,
                        Folder.state == "ACTIVE",
                    )
                    .order_by(Folder.name, Folder.id)
                    .offset(offset)
                    .limit(limit)
                )
            ]

    def get_folder(self, p: Principal, project: UUID, key: UUID) -> FolderView:
        with self.scope(p) as s:
            self.project(s, p, project)
            return FolderView.model_validate(self.folder(s, p, project, key))

    def validate_tree(
        self, s: Session, p: Principal, project: UUID, key: UUID, parent: UUID | None
    ) -> None:
        # Bounded flat snapshot; iterative traversal also verifies moved subtree depth.
        rows = list(
            s.scalars(
                select(Folder)
                .where(
                    Folder.tenant_id == p.tenant_id,
                    Folder.project_id == project,
                    Folder.state == "ACTIVE",
                )
                .limit(10001)
            )
        )
        if len(rows) >= 10000 and not any(r.id == key for r in rows):
            raise conflict("Project folder limit reached")
        tree = {row.id: row.parent_id for row in rows}
        if parent is not None and parent not in tree:
            raise missing("Folder")
        tree[key] = parent
        for start in tree:
            visited: set[UUID] = set()
            cursor: UUID | None = start
            while cursor is not None:
                if cursor in visited:
                    raise conflict("Folder cycle is not allowed")
                visited.add(cursor)
                if len(visited) > 32:
                    raise conflict("Maximum folder depth is 32")
                cursor = tree[cursor]

    def create_folder(self, p: Principal, project: UUID, body: CreateFolder) -> FolderView:
        with self.scope(p) as s:
            self.project(s, p, project, write=True)
            key = uuid4()
            self.validate_tree(s, p, project, key, body.parent_id)
            row = Folder(
                tenant_id=p.tenant_id,
                project_id=project,
                id=key,
                **body.model_dump(),
                created_by=p.principal_id,
                updated_by=p.principal_id,
            )
            s.add(row)
            self.audit(s, p, "folder_create", key)
            s.flush()
            return FolderView.model_validate(row)

    def update_folder(
        self, p: Principal, project: UUID, key: UUID, body: UpdateFolder | None, revision: int
    ) -> FolderView:
        with self.scope(p) as s:
            self.project(s, p, project, write=True)
            row = self.folder(s, p, project, key)
            expected(row, revision)
            if body:
                self.validate_tree(s, p, project, key, body.parent_id)
                row.name, row.parent_id = body.name, body.parent_id
            else:
                children = s.scalar(
                    select(Folder.id)
                    .where(
                        Folder.tenant_id == p.tenant_id,
                        Folder.project_id == project,
                        Folder.parent_id == key,
                        Folder.state == "ACTIVE",
                    )
                    .limit(1)
                )
                resources = s.scalar(
                    select(Resource.id)
                    .where(
                        Resource.tenant_id == p.tenant_id,
                        Resource.project_id == project,
                        Resource.folder_id == key,
                        Resource.state == "ACTIVE",
                    )
                    .limit(1)
                )
                if children or resources:
                    raise conflict("Archive requires an empty folder")
                row.state = "ARCHIVED"
            self.touch(s, p, row, "folder_update" if body else "folder_archive")
            return FolderView.model_validate(row)

    def destination(self, s: Session, p: Principal, project: UUID, key: UUID | None) -> None:
        if key and self.folder(s, p, project, key).state != "ACTIVE":
            raise missing("Folder")

    def register(self, s: Session, p: Principal, project: UUID, body: CreateResource) -> Resource:
        self.destination(s, p, project, body.folder_id)
        entities = HANDLERS[body.resource_type].entities(
            s, p, body.ontology_id, body.schema_version, self.authorizer
        )
        if body.entity_id not in entities:
            raise missing("Published ontology asset")
        # Do not reveal a private owner's registry ID or Project on conflict.
        if s.scalar(
            select(Resource.id).where(
                Resource.tenant_id == p.tenant_id,
                Resource.project_id == project,
                Resource.resource_type == body.resource_type,
                Resource.ontology_id == body.ontology_id,
                Resource.schema_version == body.schema_version,
                Resource.entity_id == body.entity_id,
            )
        ):
            raise conflict("Canonical asset already registered in this Project")
        row = Resource(
            tenant_id=p.tenant_id,
            project_id=project,
            id=uuid4(),
            **body.model_dump(),
            created_by=p.principal_id,
            updated_by=p.principal_id,
        )
        s.add(row)
        self.audit(s, p, "resource_create", row.id)
        s.flush()
        return row

    def create_resource(self, p: Principal, project: UUID, body: CreateResource) -> ResourceView:
        with self.scope(p) as s:
            self.project(s, p, project, write=True)
            return ResourceView.model_validate(self.register(s, p, project, body))

    def import_catalog(
        self, p: Principal, project: UUID, body: CatalogImport
    ) -> list[ResourceView]:
        with self.scope(p) as s:
            self.project(s, p, project, write=True)
            self.destination(s, p, project, body.folder_id)
            candidates = [
                (kind, key, name)
                for kind, handler in HANDLERS.items()
                for key, name in handler.entities(
                    s, p, body.ontology_id, body.schema_version, self.authorizer
                ).items()
            ]
            result = []
            for kind, key, _name in sorted(candidates)[body.offset : body.offset + body.limit]:
                old = s.scalar(
                    select(Resource).where(
                        Resource.tenant_id == p.tenant_id,
                        Resource.project_id == project,
                        Resource.resource_type == kind,
                        Resource.ontology_id == body.ontology_id,
                        Resource.schema_version == body.schema_version,
                        Resource.entity_id == key,
                    )
                )
                if old is not None:
                    if old.project_id == project and old.state == "ACTIVE":
                        result.append(ResourceView.model_validate(old))
                    continue  # No disclosure of private/shared ownership through import.
                # Include kind/entity in default display names to avoid type-name collisions.
                row = self.register(
                    s,
                    p,
                    project,
                    CreateResource.model_validate(
                        {
                            "resource_type": kind,
                            "ontology_id": body.ontology_id,
                            "schema_version": body.schema_version,
                            "entity_id": key,
                            "name": f"{key} ({kind.removeprefix('ONTOLOGY_')})"[:200],
                            "folder_id": body.folder_id,
                        }
                    ),
                )
                result.append(ResourceView.model_validate(row))
            return result

    @staticmethod
    def visible(p: Principal) -> ColumnElement[bool]:
        own = exists(
            select(ProjectMember.project_id).where(
                ProjectMember.tenant_id == p.tenant_id,
                ProjectMember.project_id == Resource.project_id,
                ProjectMember.principal_id == p.principal_id,
            )
        )
        shared = exists(
            select(ResourceShare.resource_id)
            .join(
                ProjectMember,
                (ProjectMember.tenant_id == ResourceShare.tenant_id)
                & (ProjectMember.project_id == ResourceShare.project_id),
            )
            .join(
                Project,
                (Project.tenant_id == ResourceShare.tenant_id)
                & (Project.id == ResourceShare.project_id),
            )
            .where(
                ResourceShare.tenant_id == p.tenant_id,
                ResourceShare.resource_id == Resource.id,
                ProjectMember.principal_id == p.principal_id,
                Project.state == "ACTIVE",
            )
        )
        return or_(own, shared)

    def resource(self, s: Session, p: Principal, key: UUID) -> Resource:
        row = s.scalar(
            select(Resource)
            .join(
                Project,
                (Project.tenant_id == Resource.tenant_id) & (Project.id == Resource.project_id),
            )
            .where(
                Resource.tenant_id == p.tenant_id,
                Resource.id == key,
                Resource.state == "ACTIVE",
                Project.state == "ACTIVE",
                self.visible(p),
            )
        )
        if row is None:
            raise missing("Resource")
        if row.resource_type not in (
            "ARTIFACT",
            "DATASET",
            "PIPELINE",
            "MAPPING",
            "MEDIA_SET",
            "FUNCTION",
            "AUTOMATION",
            "APPLICATION",
        ):
            self.authorizer.require(p, "schema:read", f"{p.tenant_id}/{row.ontology_id}")
        return row

    def get_resource(self, p: Principal, key: UUID) -> ResourceView:
        with self.scope(p) as s:
            return ResourceView.model_validate(self.resource(s, p, key))

    def resources(
        self,
        p: Principal,
        project: UUID,
        folder: UUID | None = None,
        search: str = "",
        limit: int = 50,
        offset: int = 0,
        shared: bool = False,
    ) -> list[ResourceView]:
        page(limit, offset)
        if len(search) > 200:
            raise ApplicationError("invalid_search", "Search exceeds 200 characters", 422)
        with self.scope(p) as s:
            row, _ = self.project(s, p, project)
            # Schema discovery is independent of Project grants, including empty pages.
            # Ontology discovery requires schema authority; artifact discovery does not.
            if row.state != "ACTIVE":
                return []
            if folder:
                self.folder(s, p, project, folder)
            query = (
                select(Resource)
                .join(
                    Project,
                    (Project.tenant_id == Resource.tenant_id) & (Project.id == Resource.project_id),
                )
                .where(
                    Resource.tenant_id == p.tenant_id,
                    Resource.state == "ACTIVE",
                    Project.state == "ACTIVE",
                    Resource.name.contains(search, autoescape=True),
                )
            )
            # Apply ontology permission before pagination to avoid private counts/holes.
            try:
                self.authorizer.require(p, "schema:read", f"{p.tenant_id}/projects/{project}")
            except ApplicationError as exc:
                if exc.status_code != 403:
                    raise
                query = query.where(
                    Resource.resource_type.in_(
                        [
                            "ARTIFACT",
                            "DATASET",
                            "PIPELINE",
                            "MAPPING",
                            "MEDIA_SET",
                            "FUNCTION",
                            "AUTOMATION",
                            "APPLICATION",
                        ]
                    )
                )
            if shared:
                query = query.where(
                    exists(
                        select(ResourceShare.resource_id).where(
                            ResourceShare.tenant_id == p.tenant_id,
                            ResourceShare.project_id == project,
                            ResourceShare.resource_id == Resource.id,
                        )
                    )
                )
            else:
                query = query.where(Resource.project_id == project, Resource.folder_id == folder)
            rows = list(
                s.scalars(query.order_by(Resource.name, Resource.id).offset(offset).limit(limit))
            )
            for item in rows:
                if item.resource_type not in (
                    "ARTIFACT",
                    "DATASET",
                    "PIPELINE",
                    "MAPPING",
                    "MEDIA_SET",
                    "FUNCTION",
                    "AUTOMATION",
                    "APPLICATION",
                ):
                    self.authorizer.require(p, "schema:read", f"{p.tenant_id}/{item.ontology_id}")
            return [ResourceView.model_validate(item) for item in rows]

    def update_resource(
        self, p: Principal, key: UUID, body: UpdateResource | None, revision: int
    ) -> ResourceView:
        with self.scope(p) as s:
            row = self.resource(s, p, key)
            self.project(s, p, row.project_id, write=True)
            expected(row, revision)
            if body:
                self.destination(s, p, row.project_id, body.folder_id)
                row.name, row.description, row.folder_id = (
                    body.name,
                    body.description,
                    body.folder_id,
                )
            else:
                row.state = "ARCHIVED"
                s.execute(
                    delete(ResourceShare).where(
                        ResourceShare.tenant_id == p.tenant_id, ResourceShare.resource_id == key
                    )
                )
            self.touch(s, p, row, "resource_update" if body else "resource_archive")
            return ResourceView.model_validate(row)

    def shares(self, p: Principal, key: UUID, limit: int = 50, offset: int = 0) -> list[ShareView]:
        page(limit, offset)
        with self.scope(p) as s:
            row = self.resource(s, p, key)
            self.project(s, p, row.project_id, manage=True)
            return [
                ShareView.model_validate(item)
                for item in s.scalars(
                    select(ResourceShare)
                    .where(ResourceShare.tenant_id == p.tenant_id, ResourceShare.resource_id == key)
                    .order_by(ResourceShare.project_id)
                    .offset(offset)
                    .limit(limit)
                )
            ]

    def share(self, p: Principal, key: UUID, body: ShareChange) -> ResourceView:
        with self.scope(p) as s:
            row = self.resource(s, p, key)
            self.project(s, p, row.project_id, manage=True)
            expected(row, body.expected_revision)
            if body.enabled:
                target, _ = self.project(s, p, body.project_id)
                if target.state != "ACTIVE" or target.id == row.project_id:
                    raise conflict("Share requires another active Project")
            old = s.get(ResourceShare, (p.tenant_id, key, body.project_id))
            if body.enabled and old is None:
                s.add(
                    ResourceShare(
                        tenant_id=p.tenant_id,
                        resource_id=key,
                        project_id=body.project_id,
                        created_by=p.principal_id,
                    )
                )
            elif not body.enabled and old:
                s.delete(old)
            self.touch(s, p, row, "share", body.model_dump(mode="json"))
            return ResourceView.model_validate(row)
