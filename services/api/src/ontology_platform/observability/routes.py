from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from ontology_platform.observability.contracts import (
    ColumnLineage,
    Dashboard,
    EventView,
    ExecutionObservation,
    FreshnessDependencies,
    FreshnessInput,
    FreshnessStatus,
    HealthSummary,
    ImpactResult,
    IndexStatus,
    LineageGraph,
    Traversal,
)
from ontology_platform.observability.service import ObservabilityService
from ontology_platform.projects.routes import Actor, Limit, Offset

router = APIRouter(prefix="/api/v1", tags=["observability"])


def service(request: Request) -> ObservabilityService:
    return ObservabilityService(
        request.app.state.sessions,
        request.app.state.authorizer,
        request.app.state.artifact_settings,
        request.app.state.artifact_store,
    )


Service = Annotated[ObservabilityService, Depends(service)]


@router.post("/lineage/traverse", response_model=LineageGraph)
def traverse(body: Traversal, actor: Actor, svc: Service) -> LineageGraph:
    return svc.graph(actor, body)


@router.post("/lineage/impact", response_model=ImpactResult)
def impact(body: Traversal, actor: Actor, svc: Service) -> ImpactResult:
    return svc.impact(actor, body)


@router.get("/resources/{resource_id}/lineage/index", response_model=IndexStatus)
def indexing(resource_id: UUID, actor: Actor, svc: Service) -> IndexStatus:
    return svc.status_index(actor, resource_id)


@router.post("/resources/{resource_id}/lineage/reconcile", response_model=IndexStatus)
def backfill(
    resource_id: UUID, actor: Actor, svc: Service, batch: Annotated[int, Query(ge=1, le=100)] = 50
) -> IndexStatus:
    return svc.backfill(actor, resource_id, batch)


@router.get(
    "/pipelines/{pipeline_id}/definitions/{definition_id}/columns", response_model=ColumnLineage
)
def columns(
    pipeline_id: UUID,
    definition_id: UUID,
    actor: Actor,
    svc: Service,
    output: Annotated[str | None, Query(max_length=80)] = None,
) -> ColumnLineage:
    return svc.columns(actor, pipeline_id, definition_id, output)


@router.get("/datasets/{dataset_id}/freshness", response_model=FreshnessStatus)
def freshness(dataset_id: UUID, actor: Actor, svc: Service) -> FreshnessStatus:
    return svc.freshness(actor, dataset_id)


@router.put("/datasets/{dataset_id}/freshness", response_model=FreshnessStatus)
def policy(dataset_id: UUID, body: FreshnessInput, actor: Actor, svc: Service) -> FreshnessStatus:
    return svc.policy(actor, dataset_id, body)


@router.get("/resources/{resource_id}/health", response_model=HealthSummary)
def health(
    resource_id: UUID, actor: Actor, svc: Service, limit: Limit = 50, offset: Offset = 0
) -> HealthSummary:
    return svc.health(actor, resource_id, limit, offset)


@router.get("/resources/{resource_id}/events", response_model=list[EventView])
def events(
    resource_id: UUID, actor: Actor, svc: Service, limit: Limit = 50, offset: Offset = 0
) -> list[EventView]:
    return svc.events(actor, resource_id, limit, offset)


@router.get("/observability/executions/{job_id}", response_model=ExecutionObservation)
def execution(job_id: UUID, actor: Actor, svc: Service) -> ExecutionObservation:
    return svc.execution(actor, job_id)


@router.get("/observability/dashboard", response_model=Dashboard)
def dashboard(
    actor: Actor, svc: Service, days: Annotated[int, Query(ge=1, le=30)] = 7
) -> Dashboard:
    return svc.dashboard(actor, days)


@router.get("/datasets/{dataset_id}/freshness/dependencies", response_model=FreshnessDependencies)
def dependency_freshness(dataset_id: UUID, actor: Actor, svc: Service) -> FreshnessDependencies:
    return svc.freshness_dependencies(actor, dataset_id)
