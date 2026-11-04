from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.mappings.contracts import (
    MappingDefinitionView,
    MappingPreview,
    MappingRun,
    MappingSpec,
)
from ontology_platform.mappings.service import MappingService
from ontology_platform.pipelines.contracts import ExecutionJobView
from ontology_platform.projects.contracts import ResourceView
from ontology_platform.projects.routes import Actor, Limit, Offset

router = APIRouter(prefix="/api/v1", tags=["mappings"])


def service(request: Request) -> MappingService:
    return MappingService(
        request.app.state.sessions,
        request.app.state.authorizer,
        request.app.state.artifact_settings,
        request.app.state.artifact_store,
    )


Service = Annotated[MappingService, Depends(service)]


@router.post("/projects/{project_id}/mappings", response_model=ResourceView, status_code=201)
def create(project_id: UUID, body: CreateArtifact, actor: Actor, svc: Service) -> ResourceView:
    return svc.create(actor, project_id, body)


@router.get("/mappings/{mapping_id}", response_model=ResourceView)
def get(mapping_id: UUID, actor: Actor, svc: Service) -> ResourceView:
    with svc.scope(actor) as s:
        return ResourceView.model_validate(svc.artifact(s, actor, mapping_id))


@router.post("/mappings/{mapping_id}/validate", response_model=MappingSpec)
def validate(mapping_id: UUID, body: MappingSpec, actor: Actor, svc: Service) -> MappingSpec:
    with svc.scope(actor) as s:
        svc.artifact(s, actor, mapping_id)
        svc.target(s, actor, body)
    return body


@router.post(
    "/mappings/{mapping_id}/definitions", response_model=MappingDefinitionView, status_code=201
)
def publish(
    mapping_id: UUID, body: MappingSpec, actor: Actor, svc: Service
) -> MappingDefinitionView:
    return svc.publish(actor, mapping_id, body)


@router.get("/mappings/{mapping_id}/definitions", response_model=list[MappingDefinitionView])
def definitions(
    mapping_id: UUID, actor: Actor, svc: Service, limit: Limit = 50, offset: Offset = 0
) -> list[MappingDefinitionView]:
    return svc.definitions(actor, mapping_id, limit, offset)


@router.get(
    "/mappings/{mapping_id}/definitions/{definition_id}", response_model=MappingDefinitionView
)
def definition(
    mapping_id: UUID, definition_id: UUID, actor: Actor, svc: Service
) -> MappingDefinitionView:
    with svc.scope(actor) as s:
        return MappingDefinitionView.model_validate(
            svc.definition(s, actor, mapping_id, definition_id)
        )


@router.post("/mappings/{mapping_id}/preview")
def preview(
    mapping_id: UUID, body: MappingRun | MappingPreview, actor: Actor, svc: Service
) -> dict[str, Any]:
    return svc.preview(actor, mapping_id, body)


@router.post("/mappings/{mapping_id}/runs", response_model=ExecutionJobView, status_code=202)
def start(mapping_id: UUID, body: MappingRun, actor: Actor, svc: Service) -> ExecutionJobView:
    return svc.start(actor, mapping_id, body)


@router.get("/mappings/{mapping_id}/runs", response_model=list[ExecutionJobView])
def history(
    mapping_id: UUID, actor: Actor, svc: Service, limit: Limit = 50, offset: Offset = 0
) -> list[ExecutionJobView]:
    return svc.history(actor, mapping_id, limit, offset)


@router.get("/materialization/runs/{run_id}/provenance")
def provenance(
    run_id: UUID, actor: Actor, svc: Service, limit: Limit = 50, offset: Offset = 0
) -> list[dict[str, Any]]:
    return svc.provenance(actor, run_id, limit, offset)


@router.get(
    "/datasets/{dataset_id}/versions/{version_id}/materializations",
    response_model=list[ExecutionJobView],
)
def sources(
    dataset_id: UUID,
    version_id: UUID,
    actor: Actor,
    svc: Service,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[ExecutionJobView]:
    return svc.source_runs(actor, dataset_id, version_id, limit, offset)


@router.get("/ontologies/{ontology_id}/objects/{type_id}/{object_id}/materializations")
def object_sources(
    ontology_id: str,
    type_id: str,
    object_id: str,
    actor: Actor,
    svc: Service,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[dict[str, Any]]:
    return svc.target_runs(
        actor, ontology_id, {"kind": "object", "type": type_id, "id": object_id}, limit, offset
    )


@router.get("/ontologies/{ontology_id}/links/{link_type}/materializations")
def link_sources(
    ontology_id: str,
    link_type: str,
    source_type: str,
    source_id: str,
    target_type: str,
    target_id: str,
    actor: Actor,
    svc: Service,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[dict[str, Any]]:
    return svc.target_runs(
        actor,
        ontology_id,
        {
            "kind": "link",
            "link_type": link_type,
            "source_type": source_type,
            "source_id": source_id,
            "target_type": target_type,
            "target_id": target_id,
        },
        limit,
        offset,
    )
