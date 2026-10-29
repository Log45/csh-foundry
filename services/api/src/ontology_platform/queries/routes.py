from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ontology_platform.dependencies import get_principal
from ontology_platform.errors import ApplicationError
from ontology_platform.queries.ast import AggregateRequest, AggregateResult, QueryPage, QueryRequest
from ontology_platform.queries.service import QueryService
from ontology_platform.security.interfaces import Principal

router = APIRouter(prefix="/api/v1", tags=["queries"])
Actor = Annotated[Principal, Depends(get_principal)]


def service(request: Request) -> QueryService:
    return QueryService(
        request.app.state.sessions, request.app.state.authorizer, request.app.state.query_cursors
    )


Queries = Annotated[QueryService, Depends(service)]


@router.post("/ontologies/{ontology_id}/objects/{type_id}/query", response_model=QueryPage)
def query_objects(
    ontology_id: str, type_id: str, body: QueryRequest, actor: Actor, queries: Queries
) -> QueryPage:
    if type_id != body.object_type:
        raise ApplicationError("object_type_mismatch", "Path and query object types differ", 422)
    return queries.query(actor, ontology_id, body)


@router.post("/ontologies/{ontology_id}/object-sets/query", response_model=QueryPage)
@router.post("/ontologies/{ontology_id}/traverse", response_model=QueryPage)
def query_set(ontology_id: str, body: QueryRequest, actor: Actor, queries: Queries) -> QueryPage:
    return queries.query(actor, ontology_id, body)


@router.post("/ontologies/{ontology_id}/aggregate", response_model=AggregateResult)
def aggregate(
    ontology_id: str, body: AggregateRequest, actor: Actor, queries: Queries
) -> AggregateResult:
    return queries.aggregate(actor, ontology_id, body)
