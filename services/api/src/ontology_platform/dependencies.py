from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ontology_platform.errors import ApplicationError
from ontology_platform.security.interfaces import Principal


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
    return resolve(
        request.app.state.sessions, issuer, subject, tenant, method=method, expires_at=expiry
    )


def verified_identity(request: Request) -> tuple[str, str, str, datetime]:
    """Verify credentials without requiring a selected tenant (membership discovery only)."""
    settings = request.app.state.settings
    if settings.auth_mode == "oidc":
        raw_credential = request.headers.get("authorization", "")
        scheme, _, token = raw_credential.partition(" ")
        if scheme.lower() != "bearer" or not token or " " in token:
            raise ApplicationError(
                "authentication_required", "Bearer authentication is required", 401
            )
        provider, claims = request.app.state.oidc.verify(token)
        issuer, subject = provider.issuer, claims["sub"]
        method, expiry = "oidc", datetime.fromtimestamp(claims["exp"], UTC)
    elif settings.auth_mode == "test":
        issuer, subject, method = settings.test_issuer, settings.test_subject, "test"
        expiry = datetime.now(UTC) + timedelta(minutes=5)
    elif settings.trusted_local_identity and settings.auth_mode in {"disabled", "local"}:
        raise ApplicationError("authentication_required", "Verified identity is required", 401)
    else:
        raise ApplicationError("authentication_required", "Authentication is required", 401)
    if expiry <= datetime.now(UTC):
        raise ApplicationError("invalid_token", "Access token expired", 401)
    return issuer, subject, method, expiry
