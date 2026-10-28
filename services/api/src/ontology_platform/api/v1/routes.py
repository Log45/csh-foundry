from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from ontology_platform.contracts import (
    Compatibility,
    CreateObject,
    LifecycleInput,
    LinkInput,
    LinkView,
    ObjectInput,
    ObjectPatch,
    ObjectView,
    OntologyView,
    PlanInput,
    PlanView,
    TenantRequest,
    TenantView,
    VersionView,
)
from ontology_platform.dependencies import get_principal
from ontology_platform.errors import ApplicationError
from ontology_platform.metadata.service import RegistryService
from ontology_platform.objects.service import ObjectService
from ontology_platform.security.interfaces import Principal
from ontology_platform.security.tenants import TenantService
from ontology_schema.models import OntologyDefinition

router = APIRouter(prefix="/api/v1")
Actor = Annotated[Principal, Depends(get_principal)]
PageSize = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


def registry(request: Request) -> RegistryService:
    return RegistryService(request.app.state.sessions, request.app.state.authorizer)


def objects(request: Request) -> ObjectService:
    return ObjectService(request.app.state.sessions, request.app.state.authorizer)


Registry = Annotated[RegistryService, Depends(registry)]
Objects = Annotated[ObjectService, Depends(objects)]


@router.post("/tenant", response_model=TenantView, status_code=201, tags=["tenant"])
def provision_tenant(body: TenantRequest, actor: Actor, request: Request) -> TenantView:
    return TenantService(request.app.state.sessions, request.app.state.authorizer).provision(
        actor, body.name
    )


@router.get("/tenant", response_model=TenantView, tags=["tenant"])
def tenant(actor: Actor, request: Request) -> TenantView:
    return TenantService(request.app.state.sessions, request.app.state.authorizer).get(actor)


@router.post("/ontologies", response_model=VersionView, status_code=201, tags=["registry"])
def create_ontology(body: OntologyDefinition, actor: Actor, service: Registry) -> VersionView:
    return service.create(actor, body)


@router.get("/ontologies", response_model=list[OntologyView], tags=["registry"])
def list_ontologies(
    actor: Actor, service: Registry, limit: PageSize = 100, offset: Offset = 0
) -> list[OntologyView]:
    return service.list_ontologies(actor, limit, offset)


@router.get("/ontologies/{ontology_id}", response_model=OntologyView, tags=["registry"])
def get_ontology(ontology_id: str, actor: Actor, service: Registry) -> OntologyView:
    return service.get(actor, ontology_id)


@router.post(
    "/ontologies/{ontology_id}/versions",
    response_model=VersionView,
    status_code=201,
    tags=["registry"],
)
def create_draft(
    ontology_id: str, body: OntologyDefinition, actor: Actor, service: Registry
) -> VersionView:
    return service.draft(actor, ontology_id, body)


@router.get(
    "/ontologies/{ontology_id}/versions", response_model=list[VersionView], tags=["registry"]
)
def list_versions(
    ontology_id: str, actor: Actor, service: Registry, limit: PageSize = 100, offset: Offset = 0
) -> list[VersionView]:
    return service.versions(actor, ontology_id, limit, offset)


@router.get(
    "/ontologies/{ontology_id}/versions/{version}", response_model=VersionView, tags=["registry"]
)
def get_version(ontology_id: str, version: str, actor: Actor, service: Registry) -> VersionView:
    return service.version(actor, ontology_id, version)


@router.put(
    "/ontologies/{ontology_id}/versions/{version}", response_model=VersionView, tags=["registry"]
)
def replace_draft(
    ontology_id: str, version: str, body: OntologyDefinition, actor: Actor, service: Registry
) -> VersionView:
    if body.version != version:
        raise ApplicationError("version_mismatch", "Path and definition versions differ", 422)
    return service.draft(actor, ontology_id, body, replace=True)


@router.post(
    "/ontologies/{ontology_id}/versions/{version}/validate",
    response_model=Compatibility,
    tags=["registry"],
)
def validate_draft(
    ontology_id: str, version: str, actor: Actor, service: Registry
) -> Compatibility:
    return service.validate(actor, ontology_id, version)


@router.post(
    "/ontologies/{ontology_id}/versions/{version}/publish",
    response_model=VersionView,
    tags=["registry"],
)
def publish(
    ontology_id: str, version: str, body: LifecycleInput, actor: Actor, service: Registry
) -> VersionView:
    return service.publish(actor, ontology_id, version, body.plan_id)


@router.post(
    "/ontologies/{ontology_id}/versions/{version}/activate",
    response_model=OntologyView,
    tags=["registry"],
)
def activate(
    ontology_id: str, version: str, body: LifecycleInput, actor: Actor, service: Registry
) -> OntologyView:
    return service.activate(actor, ontology_id, version, body.plan_id)


@router.post(
    "/ontologies/{ontology_id}/versions/{version}/migration-plans",
    response_model=PlanView,
    status_code=201,
    tags=["registry"],
)
def create_plan(
    ontology_id: str, version: str, body: PlanInput, actor: Actor, service: Registry
) -> PlanView:
    return service.create_plan(actor, ontology_id, version, body)


@router.post(
    "/ontologies/{ontology_id}/migration-plans/{plan_id}/approve",
    response_model=PlanView,
    tags=["registry"],
)
def approve_plan(ontology_id: str, plan_id: UUID, actor: Actor, service: Registry) -> PlanView:
    return service.approve_plan(actor, ontology_id, plan_id)


@router.get("/ontologies/{ontology_id}/object-types", tags=["registry"])
def get_object_types(ontology_id: str, actor: Actor, service: Registry) -> list[dict[str, object]]:
    return service.object_types(actor, ontology_id)


@router.post(
    "/ontologies/{ontology_id}/objects/{type_id}",
    response_model=ObjectView,
    status_code=201,
    tags=["objects"],
)
def create_object(
    ontology_id: str, type_id: str, body: ObjectInput, actor: Actor, service: Objects
) -> ObjectView:
    return service.create(
        actor, ontology_id, CreateObject(object_type_id=type_id, **body.model_dump())
    )


@router.get(
    "/ontologies/{ontology_id}/objects/{type_id}", response_model=ObjectView, tags=["objects"]
)
@router.get(
    "/ontologies/{ontology_id}/objects/{type_id}/{object_id}",
    response_model=ObjectView,
    tags=["objects"],
)
def get_object(
    ontology_id: str, type_id: str, object_id: str, actor: Actor, service: Objects
) -> ObjectView:
    return service.get(actor, ontology_id, type_id, object_id)


@router.patch(
    "/ontologies/{ontology_id}/objects/{type_id}", response_model=ObjectView, tags=["objects"]
)
@router.patch(
    "/ontologies/{ontology_id}/objects/{type_id}/{object_id}",
    response_model=ObjectView,
    tags=["objects"],
)
def update_object(
    ontology_id: str,
    type_id: str,
    object_id: str,
    body: ObjectPatch,
    actor: Actor,
    service: Objects,
) -> ObjectView:
    return service.patch(actor, ontology_id, type_id, object_id, body)


@router.delete("/ontologies/{ontology_id}/objects/{type_id}", status_code=204, tags=["objects"])
@router.delete(
    "/ontologies/{ontology_id}/objects/{type_id}/{object_id}", status_code=204, tags=["objects"]
)
def delete_object(
    ontology_id: str,
    type_id: str,
    object_id: str,
    actor: Actor,
    service: Objects,
    expected_version: Annotated[int, Query(ge=1)],
) -> Response:
    service.delete(actor, ontology_id, type_id, object_id, expected_version)
    return Response(status_code=204)


@router.post(
    "/ontologies/{ontology_id}/links", response_model=LinkView, status_code=201, tags=["links"]
)
def create_link(ontology_id: str, body: LinkInput, actor: Actor, service: Objects) -> LinkView:
    return service.create_link(actor, ontology_id, body)


@router.delete("/ontologies/{ontology_id}/links", status_code=204, tags=["links"])
def delete_link(ontology_id: str, body: LinkInput, actor: Actor, service: Objects) -> Response:
    service.delete_link(actor, ontology_id, body)
    return Response(status_code=204)


@router.get(
    "/ontologies/{ontology_id}/objects/{type_id}/links/{link_id}",
    response_model=list[ObjectView],
    tags=["links"],
)
@router.get(
    "/ontologies/{ontology_id}/objects/{type_id}/{object_id}/links/{link_id}",
    response_model=list[ObjectView],
    tags=["links"],
)
def neighbors(
    ontology_id: str,
    type_id: str,
    object_id: str,
    link_id: str,
    actor: Actor,
    service: Objects,
    direction: Literal["forward", "inverse"] = "forward",
    limit: PageSize = 100,
    offset: Offset = 0,
) -> list[ObjectView]:
    return service.neighbors(
        actor, ontology_id, type_id, object_id, link_id, direction, limit, offset
    )
