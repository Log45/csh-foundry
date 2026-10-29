from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse

from ontology_platform.dependencies import get_principal
from ontology_platform.interoperability.contracts import (
    ExportView,
    ImportInput,
    ImportView,
    VocabularyTerm,
)
from ontology_platform.interoperability.service import InteroperabilityService
from ontology_platform.security.interfaces import Principal
from ontology_platform.semantic.contracts import Diagnostic

router = APIRouter(prefix="/api/v1/ontologies/{ontology_id}/interchange", tags=["interchange"])
Actor = Annotated[Principal, Depends(get_principal)]


def service(request: Request) -> InteroperabilityService:
    return InteroperabilityService(request.app.state.sessions, request.app.state.authorizer)


Interchange = Annotated[InteroperabilityService, Depends(service)]


@router.post("/imports", response_model=ImportView)
def import_ontology(
    ontology_id: str, body: ImportInput, actor: Actor, svc: Interchange
) -> ImportView:
    return svc.import_ontology(actor, ontology_id, body)


@router.get("/imports/{key}", response_model=ImportView)
def get(ontology_id: str, key: UUID, actor: Actor, svc: Interchange) -> ImportView:
    return svc.get(actor, ontology_id, key)


@router.get("/imports/{key}/original", response_class=PlainTextResponse)
def original(ontology_id: str, key: UUID, actor: Actor, svc: Interchange) -> PlainTextResponse:
    return PlainTextResponse(
        svc.original(actor, ontology_id, key), headers={"X-Content-Type-Options": "nosniff"}
    )


@router.get("/imports/{key}/diagnostics", response_model=list[Diagnostic])
def diagnostics(
    ontology_id: str, key: UUID, actor: Actor, svc: Interchange, limit: int = 50, offset: int = 0
) -> list[Diagnostic]:
    return svc.diagnostics(actor, ontology_id, key, limit, offset)


@router.get("/imports/{key}/vocabulary", response_model=list[VocabularyTerm])
def vocabulary(
    ontology_id: str, key: UUID, actor: Actor, svc: Interchange, limit: int = 50, offset: int = 0
) -> list[VocabularyTerm]:
    return svc.vocabulary(actor, ontology_id, key, limit, offset)


@router.get("/exports/{version}", response_model=ExportView)
def export(ontology_id: str, version: str, actor: Actor, svc: Interchange) -> ExportView:
    return svc.export(actor, ontology_id, version)
