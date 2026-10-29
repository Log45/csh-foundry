from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ontology_platform.dependencies import get_principal
from ontology_platform.ingestion.contracts import (
    DiagnosticView,
    MappingInput,
    RunInput,
    RunView,
    SnapshotView,
    SourceInput,
)
from ontology_platform.ingestion.service import IngestionService
from ontology_platform.security.interfaces import Principal

router = APIRouter(prefix="/api/v1/ontologies/{ontology_id}", tags=["ingestion"])
Actor = Annotated[Principal, Depends(get_principal)]


def service(request: Request) -> IngestionService:
    return IngestionService(
        request.app.state.sessions,
        request.app.state.authorizer,
        request.app.state.ingestion_catalog,
    )


Ingestion = Annotated[IngestionService, Depends(service)]


@router.post("/sources", response_model=SnapshotView)
def create_source(
    ontology_id: str, body: SourceInput, actor: Actor, ingestion: Ingestion
) -> SnapshotView:
    return ingestion.create_source(actor, ontology_id, body)


@router.get("/sources", response_model=list[SnapshotView])
def sources(
    ontology_id: str, actor: Actor, ingestion: Ingestion, limit: int = 50, offset: int = 0
) -> list[SnapshotView]:
    return ingestion.sources(actor, ontology_id, limit, offset)


@router.get("/sources/{source_id}", response_model=SnapshotView)
def source(
    ontology_id: str, source_id: str, actor: Actor, ingestion: Ingestion, version: int = 1
) -> SnapshotView:
    return ingestion.get_source(actor, ontology_id, source_id, version)


@router.post("/mappings", response_model=SnapshotView)
def mapping(
    ontology_id: str, body: MappingInput, actor: Actor, ingestion: Ingestion
) -> SnapshotView:
    return ingestion.create_mapping(actor, ontology_id, body)


@router.post("/ingestion/runs", response_model=RunView)
def submit(ontology_id: str, body: RunInput, actor: Actor, ingestion: Ingestion) -> RunView:
    return ingestion.submit(actor, ontology_id, body)


@router.get("/ingestion/runs", response_model=list[RunView])
def runs(
    ontology_id: str, actor: Actor, ingestion: Ingestion, limit: int = 50, offset: int = 0
) -> list[RunView]:
    return ingestion.runs(actor, ontology_id, limit, offset)


@router.get("/ingestion/runs/{run_id}", response_model=RunView)
def run(ontology_id: str, run_id: UUID, actor: Actor, ingestion: Ingestion) -> RunView:
    return ingestion.get(actor, ontology_id, run_id)


@router.get("/ingestion/runs/{run_id}/diagnostics", response_model=list[DiagnosticView])
def diagnostics(
    ontology_id: str,
    run_id: UUID,
    actor: Actor,
    ingestion: Ingestion,
    limit: int = 50,
    offset: int = 0,
) -> list[DiagnosticView]:
    return ingestion.diagnostics(actor, ontology_id, run_id, limit, offset)


@router.post("/ingestion/runs/{run_id}/cancel", response_model=RunView)
def cancel(ontology_id: str, run_id: UUID, actor: Actor, ingestion: Ingestion) -> RunView:
    return ingestion.cancel(actor, ontology_id, run_id)
