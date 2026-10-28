"""Provision only the explicitly configured trusted local tenant."""

import argparse

from sqlalchemy.orm import sessionmaker

from ontology_platform.config import get_settings
from ontology_platform.db.session import make_engine
from ontology_platform.errors import ApplicationError
from ontology_platform.security.interfaces import Principal
from ontology_platform.security.local import LocalAuthorizer
from ontology_platform.security.tenants import TenantService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    settings = get_settings()
    if (
        not settings.trusted_local_identity
        or settings.local_tenant_id is None
        or settings.local_principal_id is None
    ):
        raise ApplicationError(
            "authentication_required", "Configure trusted local tenant and principal", 401
        )
    principal = Principal(
        tenant_id=settings.local_tenant_id, principal_id=settings.local_principal_id
    )
    engine = make_engine(settings)
    try:
        tenant = TenantService(sessionmaker(engine), LocalAuthorizer(settings)).provision(
            principal, args.name
        )
        print(f"Provisioned local tenant {tenant.id}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
