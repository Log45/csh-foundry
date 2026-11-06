from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ontology_platform.actions.contracts import ActionResult, ExecuteRequest
from ontology_platform.applications.contracts import (
    Document,
    Draft,
    Publish,
    Published,
    RuntimeQuery,
    Save,
    Validation,
)
from ontology_platform.applications.service import ApplicationService
from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.projects.contracts import ResourceView
from ontology_platform.projects.routes import Actor, Limit, Offset
from ontology_platform.queries.ast import AggregateResult, QueryPage

router = APIRouter(prefix="/api/v1", tags=["applications"])


def service(request: Request) -> ApplicationService:
    return ApplicationService(
        request.app.state.sessions, request.app.state.authorizer, request.app.state.query_cursors
    )


Service = Annotated[ApplicationService, Depends(service)]


@router.post("/projects/{project_id}/applications", response_model=ResourceView, status_code=201)
def create(project_id: UUID, body: CreateArtifact, actor: Actor, svc: Service) -> ResourceView:
    return svc.create(actor, project_id, body)


@router.get("/applications/{application_id}", response_model=ResourceView)
def get(application_id: UUID, actor: Actor, svc: Service) -> ResourceView:
    with svc.scope(actor) as s:
        return ResourceView.model_validate(svc.application(s, actor, application_id))


@router.get("/applications/{application_id}/draft", response_model=Draft | None)
def draft(application_id: UUID, actor: Actor, svc: Service) -> Draft | None:
    return svc.draft(actor, application_id)


@router.put("/applications/{application_id}/draft", response_model=Draft)
def save(application_id: UUID, body: Save, actor: Actor, svc: Service) -> Draft:
    return svc.save(actor, application_id, body)


@router.post("/applications/{application_id}/validate", response_model=Validation)
def validate(application_id: UUID, body: Document, actor: Actor, svc: Service) -> Validation:
    return svc.validate(actor, application_id, body)


@router.post("/applications/{application_id}/versions", response_model=Published, status_code=201)
def publish(application_id: UUID, body: Publish, actor: Actor, svc: Service) -> Published:
    return svc.publish(actor, application_id, body)


@router.get("/applications/{application_id}/versions", response_model=list[Published])
def versions(
    application_id: UUID, actor: Actor, svc: Service, limit: Limit = 50, offset: Offset = 0
) -> list[Published]:
    return svc.versions(actor, application_id, limit, offset)


@router.get("/applications/{application_id}/versions/{version_id}", response_model=Published)
def version(application_id: UUID, version_id: UUID, actor: Actor, svc: Service) -> Published:
    return svc.version(actor, application_id, version_id)


@router.get(
    "/applications/{application_id}/versions/{version_id}/runtime", response_model=Published
)
def runtime(application_id: UUID, version_id: UUID, actor: Actor, svc: Service) -> Published:
    return svc.version(actor, application_id, version_id)


@router.post(
    "/applications/{application_id}/versions/{version_id}/query",
    response_model=QueryPage | AggregateResult,
)
def query(
    application_id: UUID, version_id: UUID, body: RuntimeQuery, actor: Actor, svc: Service
) -> QueryPage | AggregateResult:
    return svc.query(actor, application_id, version_id, body)


@router.post(
    "/applications/{application_id}/versions/{version_id}/actions/{binding_id}/preview",
    response_model=ActionResult,
)
def preview(
    application_id: UUID,
    version_id: UUID,
    binding_id: str,
    body: ExecuteRequest,
    actor: Actor,
    svc: Service,
) -> ActionResult:
    return svc.action(actor, application_id, version_id, binding_id, body, True)


@router.post(
    "/applications/{application_id}/versions/{version_id}/actions/{binding_id}/execute",
    response_model=ActionResult,
)
def execute(
    application_id: UUID,
    version_id: UUID,
    binding_id: str,
    body: ExecuteRequest,
    actor: Actor,
    svc: Service,
) -> ActionResult:
    return svc.action(actor, application_id, version_id, binding_id, body, False)
