from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ontology_platform.dependencies import get_principal
from ontology_platform.security.interfaces import Principal
from ontology_platform.semantic.contracts import (
    ApprovalEvent,
    ApprovalInput,
    ArtifactView,
    CompileInput,
    ExportInput,
    FactView,
    JobInput,
    JobView,
    NativeInput,
)
from ontology_platform.semantic.service import SemanticService

router = APIRouter(prefix="/api/v1/ontologies/{ontology_id}/semantic", tags=["semantic"])
Actor = Annotated[Principal, Depends(get_principal)]


def service(request: Request) -> SemanticService:
    return SemanticService(request.app.state.sessions, request.app.state.authorizer)


Semantic = Annotated[SemanticService, Depends(service)]


@router.post("/compile")
def compile(ontology_id: str, body: CompileInput, actor: Actor, semantic: Semantic) -> list[UUID]:
    return semantic.compile(actor, ontology_id, body)


@router.post("/native-artifacts")
def native(ontology_id: str, body: NativeInput, actor: Actor, semantic: Semantic) -> UUID:
    return semantic.native(actor, ontology_id, body)


@router.post("/exports")
def export(ontology_id: str, body: ExportInput, actor: Actor, semantic: Semantic) -> UUID:
    return semantic.export(actor, ontology_id, body)


@router.get("/artifacts/{key}", response_model=ArtifactView)
def artifact(ontology_id: str, key: UUID, actor: Actor, semantic: Semantic) -> ArtifactView:
    return semantic.get(actor, ontology_id, key)


@router.post("/jobs", response_model=JobView)
def submit(ontology_id: str, body: JobInput, actor: Actor, semantic: Semantic) -> JobView:
    return semantic.submit(actor, ontology_id, body)


@router.get("/jobs", response_model=list[JobView])
def jobs(
    ontology_id: str, actor: Actor, semantic: Semantic, limit: int = 50, offset: int = 0
) -> list[JobView]:
    return semantic.jobs(actor, ontology_id, limit, offset)


@router.get("/jobs/{key}", response_model=JobView)
def job(ontology_id: str, key: UUID, actor: Actor, semantic: Semantic) -> JobView:
    return semantic.job(actor, ontology_id, key)


@router.post("/jobs/{key}/cancel", response_model=JobView)
def cancel(ontology_id: str, key: UUID, actor: Actor, semantic: Semantic) -> JobView:
    return semantic.cancel(actor, ontology_id, key)


@router.post("/artifacts/{key}/approval")
def approve(
    ontology_id: str, key: UUID, body: ApprovalInput, actor: Actor, semantic: Semantic
) -> str:
    return semantic.approve(actor, ontology_id, key, body)


@router.get("/artifacts/{key}/facts", response_model=list[FactView])
def facts(
    ontology_id: str, key: UUID, actor: Actor, semantic: Semantic, limit: int = 50, offset: int = 0
) -> list[FactView]:
    return semantic.facts(actor, ontology_id, key, limit, offset)


@router.get("/artifacts/{key}/approval", response_model=list[ApprovalEvent])
def approval_history(
    ontology_id: str, key: UUID, actor: Actor, semantic: Semantic, limit: int = 50, offset: int = 0
) -> list[ApprovalEvent]:
    return semantic.approval_history(actor, ontology_id, key, limit, offset)
