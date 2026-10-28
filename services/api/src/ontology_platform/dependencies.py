from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from ontology_platform.errors import ApplicationError
from ontology_platform.security.interfaces import Principal


def get_session(request: Request) -> Iterator[Session]:
    # No implicit commit: mutations must use a service-owned transaction.
    with request.app.state.sessions() as session:
        yield session


def get_principal(request: Request) -> Principal:
    settings = request.app.state.settings
    if not settings.trusted_local_identity:
        raise ApplicationError("authentication_required", "Authentication is required", 401)
    return Principal(tenant_id=settings.local_tenant_id, principal_id=settings.local_principal_id)
