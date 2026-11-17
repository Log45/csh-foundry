"""Production security administration and self introspection; no frontend login."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Security
from fastapi.security import HTTPAuthorizationCredentials

from ontology_platform.config import DirectorySource
from ontology_platform.dependencies import bearer, get_principal, verified_identity, verified_oidc
from ontology_platform.errors import ApplicationError
from ontology_platform.security.admin import SecurityAdministration
from ontology_platform.security.contracts import (
    AssignmentInput,
    DelegationInput,
    IdentityInput,
    MembershipInput,
    PolicyInput,
    RoleInput,
)
from ontology_platform.security.directory import search_users
from ontology_platform.security.interfaces import Principal
from ontology_platform.security.onboarding import OnboardingInput, OnboardingResult, onboard
from ontology_platform.security.recipient_directory import (
    DirectoryRecipient,
    RecipientPage,
    directory_scope,
    selected_username,
    selection_id,
)
from ontology_platform.security.service import PlatformAuthorizer, denied
from ontology_platform.security.sharing import (
    DirectoryClaimInput,
    DirectoryShareInput,
    DirectoryShareInvitation,
    ShareOption,
    SharingService,
    TenantShareInput,
    TenantShareView,
)

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


@router.post("/personal-tenant", response_model=OnboardingResult, response_model_exclude_unset=True)
def personal_tenant(
    request: Request,
    body: OnboardingInput | None = None,
    credential: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)] = None,
) -> OnboardingResult:
    settings = request.app.state.settings
    if settings.auth_mode != "oidc":
        raise denied()
    provider, claims, _ = verified_oidc(request)
    return onboard(request.app.state.sessions, settings, provider, claims, body)


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


@router.delete("/job-grants/{key}")
def revoke_job_grant(key: UUID, p: Actor, admin: Admin) -> dict[str, str]:
    admin.revoke_job_grant(p, str(key))
    return {"status": "revoked"}


sharing = APIRouter(prefix="/api/v1/shares", tags=["sharing"])
Search = Annotated[str, Query(max_length=100)]


@sharing.get("/targets/{target}")
def share_targets(
    p: Actor,
    admin: Admin,
    target: Literal["project", "ontology"],
    search: Search = "",
) -> list[ShareOption]:
    return SharingService(admin.auth).targets(p, target, search.strip())


@contextmanager
def directory_slot(request: Request) -> Iterator[None]:
    slots = request.app.state.directory_requests
    if not slots.acquire(blocking=False):
        raise ApplicationError("directory_busy", "Directory is busy. Try again.", 503)
    try:
        yield
    finally:
        slots.release()


def authorize_directory(p: Principal, admin: SecurityAdministration) -> SharingService:
    if p.authentication_method != "oidc":
        raise denied()
    service = SharingService(admin.auth)
    with service.scope(p) as s:
        service.directory_access(s, p)
    return service


@sharing.get("/recipients")
def share_recipients(p: Actor, admin: Admin, request: Request, search: Search) -> list[ShareOption]:
    service = authorize_directory(p, admin)
    with directory_slot(request):
        users = search_users(
            request.app.state.settings, request.app.state.oidc, p.identity_provider, search
        )
        return [
            ShareOption(id=recipient.id, label=recipient.username)
            for recipient in service.keycloak_recipients(p, users)
        ]


@sharing.get("/recipient-directory")
def recipient_directory(
    p: Actor,
    admin: Admin,
    request: Request,
    search: Search = "",
    cursor: UUID | None = None,
) -> RecipientPage:
    service = authorize_directory(p, admin)
    settings = request.app.state.settings
    sources = settings.enabled_directory_sources
    ldap = settings.ldap_provider
    if not sources:
        raise ApplicationError("directory_unconfigured", "Recipient directory is unavailable", 503)
    if cursor is not None and (
        "ldap" not in sources or ldap is None or ldap.issuer != p.identity_provider
    ):
        raise ApplicationError(
            "directory_restart", "Directory page expired. Restart the search.", 409
        )
    results: list[DirectoryRecipient] = []
    unavailable: list[DirectorySource] = []
    next_cursor = None
    active_sources: tuple[DirectorySource, ...] = ("ldap",) if cursor is not None else sources
    with directory_slot(request):
        for source in active_sources:
            try:
                if source == "ldap":
                    if ldap is None or ldap.issuer != p.identity_provider:
                        raise ApplicationError(
                            "directory_unavailable", "Directory unavailable", 503
                        )
                    people, next_cursor = request.app.state.ldap_directory.page(
                        directory_scope(p), search.strip(), cursor
                    )
                    results.extend(
                        DirectoryRecipient(
                            source="ldap",
                            id=selection_id(
                                request.app.state.directory_selections, p, person.username
                            ),
                            username=person.username,
                            display_name=person.display_name,
                        )
                        for person in people
                    )
                else:
                    users = search_users(
                        settings, request.app.state.oidc, p.identity_provider, search
                    )
                    results.extend(service.keycloak_recipients(p, users))
            except ApplicationError as error:
                if cursor is not None or error.status_code != 503:
                    raise
                unavailable.append(source)
    return RecipientPage(results=results, next_cursor=next_cursor, unavailable_sources=unavailable)


@sharing.delete("/recipient-directory")
def cancel_recipient_directory(p: Actor, request: Request, cursor: UUID) -> dict[str, str]:
    if p.authentication_method != "oidc" or p.principal_type != "user" or p.share_id:
        raise denied()
    request.app.state.ldap_directory.cancel(cursor, directory_scope(p))
    return {"status": "cancelled"}


@sharing.post("/directory-invitations", status_code=201)
def invite_directory(
    p: Actor,
    admin: Admin,
    request: Request,
    body: DirectoryShareInput,
) -> DirectoryShareInvitation:
    settings = request.app.state.settings
    provider = settings.ldap_provider
    if (
        "ldap" not in settings.enabled_directory_sources
        or provider is None
        or provider.issuer != p.identity_provider
    ):
        raise denied()
    username = selected_username(request.app.state.directory_selections, p, body.selection)
    return SharingService(admin.auth).invite_directory(p, body, username)


@sharing.post("/{share_id}/claim")
def claim_directory(
    p: Actor,
    admin: Admin,
    share_id: UUID,
    body: DirectoryClaimInput,
) -> TenantShareView:
    return SharingService(admin.auth).claim_directory(p, share_id, p.verified_username, body.secret)


@sharing.get("", response_model=list[TenantShareView])
def shares(
    p: Actor,
    admin: Admin,
    direction: Literal["incoming", "outgoing"],
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[TenantShareView]:
    return SharingService(admin.auth).list(p, direction, limit, offset)


@sharing.post("", response_model=TenantShareView, status_code=201)
def invite(p: Actor, admin: Admin, body: TenantShareInput) -> TenantShareView:
    return SharingService(admin.auth).invite(p, body)


@sharing.post("/{share_id}/accept", response_model=TenantShareView)
def accept(p: Actor, admin: Admin, share_id: UUID) -> TenantShareView:
    return SharingService(admin.auth).transition(p, share_id, accept=True)


@sharing.delete("/{share_id}", response_model=TenantShareView)
def revoke_share(p: Actor, admin: Admin, share_id: UUID) -> TenantShareView:
    return SharingService(admin.auth).transition(p, share_id, accept=False)
