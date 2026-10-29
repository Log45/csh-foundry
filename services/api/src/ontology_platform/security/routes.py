"""Production security administration and self introspection; no frontend login."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Security
from fastapi.security import HTTPAuthorizationCredentials

from ontology_platform.dependencies import bearer, get_principal, verified_identity
from ontology_platform.security.admin import SecurityAdministration
from ontology_platform.security.contracts import (
    AssignmentInput,
    DelegationInput,
    IdentityInput,
    MembershipInput,
    PolicyInput,
    RoleInput,
)
from ontology_platform.security.interfaces import Principal
from ontology_platform.security.service import PlatformAuthorizer, denied

router = APIRouter(prefix="/api/v1/security", tags=["security"])
Actor = Annotated[Principal, Depends(get_principal)]


def service(request: Request) -> SecurityAdministration:
    auth = request.app.state.authorizer
    if not isinstance(auth, PlatformAuthorizer):
        raise denied()
    return SecurityAdministration(auth)


Admin = Annotated[SecurityAdministration, Depends(service)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=10000)]


@router.get("/me")
def me(p: Actor, admin: Admin) -> dict[str, object]:
    return admin.effective(p)


@router.get("/roles")
def roles(
    p: Actor, admin: Admin, limit: Limit = 100, offset: Offset = 0
) -> list[dict[str, object]]:
    return admin.roles(p, limit, offset)


@router.post("/roles", status_code=201)
def role(p: Actor, admin: Admin, body: RoleInput) -> dict[str, str]:
    admin.role(p, body)
    return {"id": body.id}


@router.post("/assignments")
def assign(p: Actor, admin: Admin, body: AssignmentInput) -> dict[str, str]:
    admin.assign(p, body)
    return {"status": "assigned"}


@router.delete("/assignments")
def revoke(p: Actor, admin: Admin, body: AssignmentInput) -> dict[str, str]:
    admin.assign(p, body, revoke=True)
    return {"status": "revoked"}


@router.post("/identities", status_code=201)
def identity(p: Actor, admin: Admin, body: IdentityInput, request: Request) -> dict[str, str]:
    if request.app.state.settings.auth_mode == "oidc" and body.issuer not in {
        provider.issuer for provider in request.app.state.settings.oidc_providers
    }:
        raise denied()
    return {"principal_id": admin.identity(p, body)}


@router.put("/memberships/{key}")
def member(p: Actor, admin: Admin, key: str, body: MembershipInput) -> dict[str, str]:
    admin.member(p, key, body)
    return {"status": "updated"}


@router.post("/policies")
def policy(p: Actor, admin: Admin, body: PolicyInput) -> dict[str, int]:
    return {"version": admin.policy(p, body)}


@router.put("/delegations")
def delegate(p: Actor, admin: Admin, body: DelegationInput) -> dict[str, str]:
    admin.delegate(p, body)
    return {"status": "updated"}


@router.get("/audit")
def audit(
    p: Actor, admin: Admin, limit: Limit = 100, offset: Offset = 0
) -> list[dict[str, object]]:
    return admin.audit(p, limit, offset)


@router.get("/policies")
def policies(
    p: Actor, admin: Admin, limit: Limit = 100, offset: Offset = 0
) -> list[dict[str, object]]:
    return admin.policies(p, limit, offset)


@router.get("/memberships")
def memberships(
    p: Actor, admin: Admin, limit: Limit = 100, offset: Offset = 0
) -> list[dict[str, object]]:
    return admin.memberships(p, limit, offset)


@router.get("/tenants", response_model=list[dict[str, str]])
def own_tenants(
    request: Request,
    limit: Limit = 100,
    offset: Offset = 0,
    credential: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)] = None,
) -> list[dict[str, str]]:
    """List only enabled memberships of a verified identity, before tenant selection."""
    from ontology_platform.security.identity import own_tenants as discover

    issuer, subject, _, _ = verified_identity(request)
    return discover(request.app.state.sessions, issuer, subject, limit, offset)
