from ontology_platform.contracts import TenantView
from ontology_platform.db.governance import GovernedService
from ontology_platform.db.models import Tenant
from ontology_platform.errors import ApplicationError
from ontology_platform.security.interfaces import Principal


class TenantService(GovernedService):
    def provision(self, principal: Principal, name: str) -> TenantView:
        if not name.strip() or len(name) > 200:
            raise ApplicationError(
                "invalid_tenant", "Tenant name must contain 1–200 characters", 422
            )
        with self.operation(principal, "tenant:provision", "tenant", provision=True) as session:
            if session.get(Tenant, principal.tenant_id) is not None:
                raise ApplicationError("tenant_exists", "Tenant already provisioned", 409)
            row = Tenant(id=principal.tenant_id, name=name)
            session.add(row)
            session.flush()
            return TenantView.model_validate(row)

    def get(self, principal: Principal) -> TenantView:
        with self.operation(principal, "tenant:read", "tenant") as session:
            return TenantView.model_validate(session.get(Tenant, principal.tenant_id))
