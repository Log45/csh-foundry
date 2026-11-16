from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ontology_platform.errors import ApplicationError
from ontology_platform.security.interfaces import Principal
from ontology_platform.security.oidc import Provider


def get_session(request: Request) -> Iterator[Session]:
    # No implicit commit: mutations must use a service-owned transaction.
    with request.app.state.sessions() as session:
        yield session


bearer = HTTPBearer(auto_error=False)


def get_principal(
    request: Request,
    credential: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)] = None,
) -> Principal:
    from ontology_platform.security.identity import resolve

    settings = request.app.state.settings
    share_headers = request.headers.getlist("x-resource-share")
    if share_headers and (
        settings.auth_mode not in {"oidc", "test"} or not request.headers.get("x-tenant-id")
    ):
        raise ApplicationError("forbidden", "An explicit acting tenant is required", 403)
    if settings.trusted_local_identity and settings.auth_mode in {"disabled", "local"}:
        return Principal(
            tenant_id=settings.local_tenant_id, principal_id=settings.local_principal_id
        )
    issuer, subject, method, expiry = verified_identity(request)
    selected = request.headers.get("x-tenant-id")
    try:
        tenant = UUID(selected) if selected else None
    except ValueError as exc:
        raise ApplicationError("forbidden", "Invalid tenant selection", 403) from exc
    p = resolve(
        request.app.state.sessions, issuer, subject, tenant, method=method, expires_at=expiry
    )
    if share_headers:
        from ontology_platform.security.sharing import share_principal

        try:
            if len(share_headers) != 1:
                raise ValueError("Only one resource share can be selected")
            resource_share = UUID(share_headers[0])
        except ValueError as exc:
            raise ApplicationError("forbidden", "Invalid resource share", 403) from exc

        route = request.scope.get("route")
        with request.app.state.sessions() as session:
            return share_principal(
                session,
                p,
                resource_share,
                request.method,
                getattr(route, "path", ""),
                request.path_params,
            )
    return p


def verified_oidc(request: Request) -> tuple[Provider, dict[str, Any], datetime]:
    raw = request.headers.get("authorization", "")
    scheme, _, token = raw.partition(" ")
    if scheme.lower() != "bearer" or not token or " " in token:
        raise ApplicationError("authentication_required", "Bearer authentication is required", 401)
    from ontology_platform.diagnostics import stage

    with stage("authentication_seconds"):
        provider, claims = request.app.state.oidc.verify(token)
    expiry = datetime.fromtimestamp(claims["exp"], UTC)
    if expiry <= datetime.now(UTC):
        raise ApplicationError("invalid_token", "Access token expired", 401)
    limit_identity(request, provider.issuer, claims["sub"])
    return provider, claims, expiry


def limit_identity(request: Request, issuer: str, subject: str) -> None:
    settings = request.app.state.settings
    if settings.environment == "production":
        from ontology_platform.operations import rate_limit

        rate_limit(
            request.app.state.sessions, issuer + "\0" + subject, settings.request_limit_per_minute
        )


def verified_identity(request: Request) -> tuple[str, str, str, datetime]:
    """Verify credentials independently of tenant membership."""
    settings = request.app.state.settings
    if settings.auth_mode == "oidc":
        provider, claims, expiry = verified_oidc(request)
        return provider.issuer, claims["sub"], "oidc", expiry
    if settings.auth_mode == "test":
        limit_identity(request, settings.test_issuer, settings.test_subject)
        return (
            settings.test_issuer,
            settings.test_subject,
            "test",
            datetime.now(UTC) + timedelta(minutes=5),
        )
    raise ApplicationError("authentication_required", "Verified identity is required", 401)
