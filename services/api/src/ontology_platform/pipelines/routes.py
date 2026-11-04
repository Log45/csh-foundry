from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.pipelines.contracts import (
    Definition,
    DefinitionView,
    ExecutionJobView,
    StartRun,
)
from ontology_platform.pipelines.service import PipelineService
from ontology_platform.projects.contracts import ResourceView
from ontology_platform.projects.routes import Actor, Limit, Offset

router = APIRouter(prefix="/api/v1", tags=["pipelines"])


def service(request: Request) -> PipelineService:
    return PipelineService(
        request.app.state.sessions,
        request.app.state.authorizer,
        request.app.state.artifact_settings,
        request.app.state.artifact_store,
    )


Service = Annotated[PipelineService, Depends(service)]


@router.post("/projects/{project_id}/pipelines", response_model=ResourceView, status_code=201)
def create(project_id: UUID, body: CreateArtifact, actor: Actor, svc: Service) -> ResourceView:
    return svc.create(actor, project_id, body)


@router.get("/pipelines/{pipeline_id}", response_model=ResourceView)
def get(pipeline_id: UUID, actor: Actor, svc: Service) -> ResourceView:
    with svc.scope(actor) as session:
        return ResourceView.model_validate(svc.artifact(session, actor, pipeline_id))


@router.post("/pipelines/{pipeline_id}/validate", response_model=Definition)
def validate(pipeline_id: UUID, body: Definition, actor: Actor, svc: Service) -> Definition:
    with svc.scope(actor) as session:
        svc.artifact(session, actor, pipeline_id)
    return body


@router.post("/pipelines/{pipeline_id}/definitions", response_model=DefinitionView, status_code=201)
def publish(pipeline_id: UUID, body: Definition, actor: Actor, svc: Service) -> DefinitionView:
    return svc.publish(actor, pipeline_id, body)


@router.get("/pipelines/{pipeline_id}/definitions", response_model=list[DefinitionView])
def definitions(
    pipeline_id: UUID, actor: Actor, svc: Service, limit: Limit = 50, offset: Offset = 0
) -> list[DefinitionView]:
    return svc.definitions(actor, pipeline_id, limit, offset)


@router.post("/pipelines/{pipeline_id}/runs", response_model=ExecutionJobView, status_code=202)
def start(pipeline_id: UUID, body: StartRun, actor: Actor, svc: Service) -> ExecutionJobView:
    return svc.start(actor, pipeline_id, body)


@router.get("/pipelines/{pipeline_id}/runs", response_model=list[ExecutionJobView])
def history(
    pipeline_id: UUID, actor: Actor, svc: Service, limit: Limit = 50, offset: Offset = 0
) -> list[ExecutionJobView]:
    return svc.history(actor, pipeline_id, limit, offset)


@router.get("/execution/jobs/{job_id}", response_model=ExecutionJobView)
def status(job_id: UUID, actor: Actor, svc: Service) -> ExecutionJobView:
    return svc.status(actor, job_id)


@router.post("/execution/jobs/{job_id}/cancel", response_model=ExecutionJobView)
def cancel(job_id: UUID, actor: Actor, svc: Service) -> ExecutionJobView:
    return svc.change(actor, job_id)


@router.post("/execution/jobs/{job_id}/retry", response_model=ExecutionJobView)
def retry(job_id: UUID, actor: Actor, svc: Service) -> ExecutionJobView:
    return svc.change(actor, job_id, retry=True)


@router.get("/datasets/{dataset_id}/versions/{version_id}/lineage")
def lineage(
    dataset_id: UUID, version_id: UUID, actor: Actor, svc: Service, limit: Limit = 50
) -> list[dict[str, object]]:
    return svc.lineage(actor, dataset_id, version_id, limit)


@router.get("/pipelines/{pipeline_id}/definitions/{definition_id}", response_model=DefinitionView)
def definition(
    pipeline_id: UUID, definition_id: UUID, actor: Actor, svc: Service
) -> DefinitionView:
    with svc.scope(actor) as session:
        return DefinitionView.model_validate(
            svc.definition(session, actor, pipeline_id, definition_id)
        )
