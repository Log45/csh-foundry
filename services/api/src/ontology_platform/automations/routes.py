from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.automations.contracts import (
    AutomationDefinition,
    AutomationDefinitionView,
    Enable,
    Manual,
    ReceiptView,
    ScheduleView,
)
from ontology_platform.automations.service import AutomationService
from ontology_platform.functions.contracts import GovernedDefinitionView
from ontology_platform.projects.contracts import ResourceView
from ontology_platform.projects.routes import Actor, Limit, Offset

router = APIRouter(prefix="/api/v1", tags=["automations"])


def service(request: Request) -> AutomationService:
    return AutomationService(
        request.app.state.sessions,
        request.app.state.authorizer,
        request.app.state.artifact_settings,
        request.app.state.artifact_store,
    )


Service = Annotated[AutomationService, Depends(service)]


@router.post("/projects/{project_id}/automations", response_model=ResourceView, status_code=201)
def create(project_id: UUID, body: CreateArtifact, actor: Actor, svc: Service) -> ResourceView:
    return svc.create(actor, project_id, body)


@router.get("/automations/{automation_id}", response_model=ResourceView)
def get(automation_id: UUID, actor: Actor, svc: Service) -> ResourceView:
    with svc.scope(actor) as s:
        return ResourceView.model_validate(svc.artifact(s, actor, automation_id))


@router.post("/automations/{automation_id}/validate", response_model=AutomationDefinition)
def validate(
    automation_id: UUID, body: AutomationDefinition, actor: Actor, svc: Service
) -> AutomationDefinition:
    with svc.scope(actor) as s:
        svc.artifact(s, actor, automation_id, True)
        svc.validate_target(s, actor, body.model_dump(mode="json"))
        return body


@router.post(
    "/automations/{automation_id}/definitions",
    response_model=AutomationDefinitionView,
    status_code=201,
)
def publish(
    automation_id: UUID, body: AutomationDefinition, actor: Actor, svc: Service
) -> GovernedDefinitionView:
    return svc.publish_automation(actor, automation_id, body)


@router.get(
    "/automations/{automation_id}/definitions", response_model=list[AutomationDefinitionView]
)
def definitions(
    automation_id: UUID, actor: Actor, svc: Service, limit: Limit = 50, offset: Offset = 0
) -> list[GovernedDefinitionView]:
    return svc.published_definitions(actor, automation_id, limit, offset)


@router.get(
    "/automations/{automation_id}/definitions/{definition_id}",
    response_model=AutomationDefinitionView,
)
def definition(
    automation_id: UUID, definition_id: UUID, actor: Actor, svc: Service
) -> GovernedDefinitionView:
    with svc.scope(actor) as s:
        row = svc.governed_definition(s, actor, automation_id, definition_id)
        svc.validate_target(s, actor, row.specification)
        result = GovernedDefinitionView.model_validate(row)
        return result


@router.put("/automations/{automation_id}/activation", response_model=ScheduleView)
def enable(automation_id: UUID, body: Enable, actor: Actor, svc: Service) -> ScheduleView:
    return svc.enable(actor, automation_id, body)


@router.get("/automations/{automation_id}/schedule", response_model=ScheduleView)
def schedule(automation_id: UUID, actor: Actor, svc: Service) -> ScheduleView:
    return svc.schedule(actor, automation_id)


@router.post("/automations/{automation_id}/trigger", response_model=ReceiptView, status_code=202)
def trigger(automation_id: UUID, body: Manual, actor: Actor, svc: Service) -> ReceiptView:
    return svc.manual(actor, automation_id, body.idempotency_key)


@router.get("/automations/{automation_id}/runs", response_model=list[ReceiptView])
def history(
    automation_id: UUID, actor: Actor, svc: Service, limit: Limit = 50, offset: Offset = 0
) -> list[ReceiptView]:
    return svc.history_receipts(actor, automation_id, limit, offset)
