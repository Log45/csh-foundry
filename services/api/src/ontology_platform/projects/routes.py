from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from ontology_platform.dependencies import get_principal
from ontology_platform.projects.contracts import (
    CatalogImport,
    CreateFolder,
    CreateProject,
    CreateResource,
    Expected,
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
from ontology_platform.projects.service import ProjectService
from ontology_platform.security.interfaces import Principal

router = APIRouter(prefix="/api/v1", tags=["projects"])
Actor = Annotated[Principal, Depends(get_principal)]


def service(request: Request) -> ProjectService:
    return ProjectService(request.app.state.sessions, request.app.state.authorizer)


Service = Annotated[ProjectService, Depends(service)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=10000)]


@router.post("/projects", response_model=ProjectView, status_code=201)
def create_project(body: CreateProject, actor: Actor, svc: Service) -> ProjectView:
    return svc.create_project(actor, body)


@router.get("/projects", response_model=list[ProjectView])
def projects(
    actor: Actor, svc: Service, limit: Limit = 50, offset: Offset = 0
) -> list[ProjectView]:
    return svc.list_projects(actor, limit, offset)


@router.get("/projects/{project_id}", response_model=ProjectView)
def project(project_id: UUID, actor: Actor, svc: Service) -> ProjectView:
    return svc.get_project(actor, project_id)


@router.patch("/projects/{project_id}", response_model=ProjectView)
def update_project(
    project_id: UUID, body: UpdateProject, actor: Actor, svc: Service
) -> ProjectView:
    return svc.update_project(actor, project_id, body, body.expected_revision)


@router.post("/projects/{project_id}/archive", response_model=ProjectView)
def archive_project(project_id: UUID, body: Expected, actor: Actor, svc: Service) -> ProjectView:
    return svc.update_project(actor, project_id, None, body.expected_revision)


@router.get("/projects/{project_id}/members", response_model=list[MemberView])
def members(
    project_id: UUID, actor: Actor, svc: Service, limit: Limit = 50, offset: Offset = 0
) -> list[MemberView]:
    return svc.members(actor, project_id, limit, offset)


@router.put("/projects/{project_id}/members", response_model=ProjectView)
def member(project_id: UUID, body: MemberChange, actor: Actor, svc: Service) -> ProjectView:
    return svc.member(actor, project_id, body)


@router.get("/projects/{project_id}/folders", response_model=list[FolderView])
def folders(
    project_id: UUID,
    actor: Actor,
    svc: Service,
    parent_id: UUID | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[FolderView]:
    return svc.folders(actor, project_id, parent_id, limit, offset)


@router.post("/projects/{project_id}/folders", response_model=FolderView, status_code=201)
def create_folder(project_id: UUID, body: CreateFolder, actor: Actor, svc: Service) -> FolderView:
    return svc.create_folder(actor, project_id, body)


@router.get("/projects/{project_id}/folders/{folder_id}", response_model=FolderView)
def folder(project_id: UUID, folder_id: UUID, actor: Actor, svc: Service) -> FolderView:
    return svc.get_folder(actor, project_id, folder_id)


@router.patch("/projects/{project_id}/folders/{folder_id}", response_model=FolderView)
def update_folder(
    project_id: UUID, folder_id: UUID, body: UpdateFolder, actor: Actor, svc: Service
) -> FolderView:
    return svc.update_folder(actor, project_id, folder_id, body, body.expected_revision)


@router.post("/projects/{project_id}/folders/{folder_id}/archive", response_model=FolderView)
def archive_folder(
    project_id: UUID, folder_id: UUID, body: Expected, actor: Actor, svc: Service
) -> FolderView:
    return svc.update_folder(actor, project_id, folder_id, None, body.expected_revision)


@router.get("/projects/{project_id}/resources", response_model=list[ResourceView])
def resources(
    project_id: UUID,
    actor: Actor,
    svc: Service,
    folder_id: UUID | None = None,
    search: Annotated[str, Query(max_length=200)] = "",
    shared: bool = False,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[ResourceView]:
    return svc.resources(actor, project_id, folder_id, search, limit, offset, shared)


@router.post("/projects/{project_id}/resources", response_model=ResourceView, status_code=201)
def create_resource(
    project_id: UUID, body: CreateResource, actor: Actor, svc: Service
) -> ResourceView:
    return svc.create_resource(actor, project_id, body)


@router.post("/projects/{project_id}/catalog-import", response_model=list[ResourceView])
def catalog(
    project_id: UUID, body: CatalogImport, actor: Actor, svc: Service
) -> list[ResourceView]:
    return svc.import_catalog(actor, project_id, body)


@router.get("/resources/{resource_id}", response_model=ResourceView)
def resource(resource_id: UUID, actor: Actor, svc: Service) -> ResourceView:
    return svc.get_resource(actor, resource_id)


@router.patch("/resources/{resource_id}", response_model=ResourceView)
def update_resource(
    resource_id: UUID, body: UpdateResource, actor: Actor, svc: Service
) -> ResourceView:
    return svc.update_resource(actor, resource_id, body, body.expected_revision)


@router.post("/resources/{resource_id}/archive", response_model=ResourceView)
def archive_resource(resource_id: UUID, body: Expected, actor: Actor, svc: Service) -> ResourceView:
    return svc.update_resource(actor, resource_id, None, body.expected_revision)


@router.get("/resources/{resource_id}/shares", response_model=list[ShareView])
def shares(
    resource_id: UUID, actor: Actor, svc: Service, limit: Limit = 50, offset: Offset = 0
) -> list[ShareView]:
    return svc.shares(actor, resource_id, limit, offset)


@router.put("/resources/{resource_id}/shares", response_model=ResourceView)
def share(resource_id: UUID, body: ShareChange, actor: Actor, svc: Service) -> ResourceView:
    return svc.share(actor, resource_id, body)
