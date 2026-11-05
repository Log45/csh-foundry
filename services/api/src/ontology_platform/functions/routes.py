from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.functions.contracts import (
    FunctionDefinition,
    FunctionDefinitionView,
    GovernedDefinitionView,
    Invoke,
    ResultView,
)
from ontology_platform.functions.service import FunctionService
from ontology_platform.pipelines.contracts import ExecutionJobView
from ontology_platform.projects.contracts import ResourceView
from ontology_platform.projects.routes import Actor, Limit, Offset

router = APIRouter(prefix="/api/v1", tags=["functions"])


def service(request: Request) -> FunctionService:
    return FunctionService(
        request.app.state.sessions,
        request.app.state.authorizer,
        request.app.state.artifact_settings,
        request.app.state.artifact_store,
    )


Service = Annotated[FunctionService, Depends(service)]


@router.post("/projects/{project_id}/functions", response_model=ResourceView, status_code=201)
def create(project_id: UUID, body: CreateArtifact, actor: Actor, svc: Service) -> ResourceView:
    return svc.create(actor, project_id, body)


@router.get("/functions/{function_id}", response_model=ResourceView)
def get(function_id: UUID, actor: Actor, svc: Service) -> ResourceView:
    with svc.scope(actor) as s:
        return ResourceView.model_validate(svc.artifact(s, actor, function_id))


@router.post("/functions/{function_id}/validate", response_model=FunctionDefinition)
def validate(
    function_id: UUID, body: FunctionDefinition, actor: Actor, svc: Service
) -> FunctionDefinition:
    with svc.scope(actor) as s:
        svc.artifact(s, actor, function_id, True)
        return body


@router.post(
    "/functions/{function_id}/definitions", response_model=FunctionDefinitionView, status_code=201
)
def publish(
    function_id: UUID, body: FunctionDefinition, actor: Actor, svc: Service
) -> GovernedDefinitionView:
    return svc.publish_function(actor, function_id, body)


@router.get("/functions/{function_id}/definitions", response_model=list[FunctionDefinitionView])
def definitions(
    function_id: UUID, actor: Actor, svc: Service, limit: Limit = 50, offset: Offset = 0
) -> list[GovernedDefinitionView]:
    return svc.published_definitions(actor, function_id, limit, offset)


@router.get(
    "/functions/{function_id}/definitions/{definition_id}", response_model=FunctionDefinitionView
)
def definition(
    function_id: UUID, definition_id: UUID, actor: Actor, svc: Service
) -> GovernedDefinitionView:
    with svc.scope(actor) as s:
        row = svc.governed_definition(s, actor, function_id, definition_id)
        result = GovernedDefinitionView.model_validate(row)
        return result


@router.post("/functions/{function_id}/runs", response_model=ExecutionJobView, status_code=202)
def invoke(function_id: UUID, body: Invoke, actor: Actor, svc: Service) -> ExecutionJobView:
    return svc.invoke(actor, function_id, body)


@router.get("/functions/{function_id}/runs", response_model=list[ExecutionJobView])
def history(
    function_id: UUID, actor: Actor, svc: Service, limit: Limit = 50, offset: Offset = 0
) -> list[ExecutionJobView]:
    return svc.history(actor, function_id, limit, offset)


@router.get("/function-runs/{job_id}/result", response_model=ResultView)
def result(job_id: UUID, actor: Actor, svc: Service) -> ResultView:
    return svc.result(actor, job_id)


@router.get("/function-runs/{job_id}/provenance")
def provenance(job_id: UUID, actor: Actor, svc: Service) -> dict[str, object]:
    return svc.provenance(actor, job_id)
