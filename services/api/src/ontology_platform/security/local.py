"""Explicitly trusted local identity; no client header can select another tenant."""

from ontology_platform.config import Settings
from ontology_platform.errors import ApplicationError
from ontology_platform.security.interfaces import Principal


class LocalAuthorizer:
    def __init__(self, settings: Settings):
        self.settings = settings

    def require(self, principal: Principal, operation: str, resource: str) -> None:
        if not self.settings.trusted_local_identity or principal is None:
            raise ApplicationError(
                "authentication_required", "Trusted local identity required", 401
            )
        if (
            principal.tenant_id != self.settings.local_tenant_id
            or principal.principal_id != self.settings.local_principal_id
            or not principal.principal_id.strip()
            or not resource.startswith(f"{principal.tenant_id}/")
        ):
            raise ApplicationError("forbidden", "Principal cannot access this tenant", 403)
