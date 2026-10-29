from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ontology_platform.actions.contracts import (
    ActionRequest,
    ActionResult,
    Change,
    ExecuteRequest,
    ExecutionView,
    HistoryPage,
)
from ontology_platform.actions.service import ActionExecutionService
from ontology_platform.dependencies import get_principal
from ontology_platform.security.interfaces import Principal

router = APIRouter(prefix="/api/v1/ontologies/{ontology_id}/actions", tags=["actions"])
Actor = Annotated[Principal, Depends(get_principal)]


def service(request: Request) -> ActionExecutionService:
    return ActionExecutionService(request.app.state.sessions, request.app.state.authorizer)


Actions = Annotated[ActionExecutionService, Depends(service)]


@router.get("/executions", response_model=HistoryPage)
def history(
    ontology_id: str, actor: Actor, actions: Actions, limit: int = 50, offset: int = 0
) -> HistoryPage:
    return actions.history(actor, ontology_id, limit, offset)


@router.get("/executions/{execution_id}", response_model=ExecutionView)
def execution(
    ontology_id: str, execution_id: UUID, actor: Actor, actions: Actions
) -> ExecutionView:
    return actions.get_execution(actor, ontology_id, execution_id)


@router.get("/executions/{execution_id}/audit", response_model=list[Change])
def audit(ontology_id: str, execution_id: UUID, actor: Actor, actions: Actions) -> list[Change]:
    return actions.audit(actor, ontology_id, execution_id)


@router.post("/{action_id}/preview", response_model=ActionResult)
def preview(
    ontology_id: str, action_id: str, body: ActionRequest, actor: Actor, actions: Actions
) -> ActionResult:
    return actions.preview(actor, ontology_id, action_id, body)


@router.post("/{action_id}/execute", response_model=ActionResult)
def execute(
    ontology_id: str, action_id: str, body: ExecuteRequest, actor: Actor, actions: Actions
) -> ActionResult:
    return actions.execute(actor, ontology_id, action_id, body)
