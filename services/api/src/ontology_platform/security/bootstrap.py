"""Offline first administrator provisioning. Requires trusted database operator access."""

import argparse
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.config import get_settings
from ontology_platform.db.models import (
    ExternalIdentity,
    Membership,
    PlatformPrincipal,
    Role,
    RoleAssignment,
    SecurityState,
    Tenant,
)
from ontology_platform.db.session import make_engine
from ontology_platform.errors import ApplicationError
from ontology_platform.security.contracts import DEFAULT_ROLES, PERMISSIONS


def bootstrap(session: Session, tenant: UUID, issuer: str, subject: str, name: str) -> str:
    # Explicit one-time operation; never called at API startup or from a token resolver.
    row = session.get(Tenant, tenant, with_for_update=True)
    if row is None:
        session.add(Tenant(id=tenant, name=name))
        session.flush()
    state = session.get(SecurityState, tenant)
    if state is not None:
        # The migration creates empty states for preexisting tenants. Only initialize once.
        from sqlalchemy import select

        if session.scalar(
            select(Membership.principal_id).where(Membership.tenant_id == tenant).limit(1)
        ):
            raise ApplicationError(
                "security_initialized", "Tenant security is already initialized", 409
            )
    else:
        session.add(SecurityState(tenant_id=tenant))
        session.flush()
    binding = session.get(ExternalIdentity, (issuer, subject))
    if binding is None:
        key = str(uuid4())
        session.add(PlatformPrincipal(id=key, principal_type="user", enabled=True))
        session.flush()
        session.add(ExternalIdentity(issuer=issuer, subject=subject, principal_id=key))
    else:
        key = binding.principal_id
    session.add(Membership(tenant_id=tenant, principal_id=key, enabled=True, attributes={}))
    session.add(Role(tenant_id=tenant, id="tenant-administrator", permissions=sorted(PERMISSIONS)))
    for role_id, permissions in DEFAULT_ROLES.items():
        session.add(Role(tenant_id=tenant, id=role_id, permissions=list(permissions)))
    session.flush()
    session.add(RoleAssignment(tenant_id=tenant, principal_id=key, role_id="tenant-administrator"))
    return key


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision the first platform security administrator"
    )
    parser.add_argument("--tenant", required=True, type=UUID)
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    settings = get_settings()
    if settings.auth_mode != "oidc" or args.issuer not in {
        p.issuer for p in settings.oidc_providers
    }:
        parser.error("OIDC mode and an explicitly trusted issuer are required")
    engine = make_engine(settings)
    try:
        with sessionmaker(engine).begin() as session:
            key = bootstrap(session, args.tenant, args.issuer, args.subject, args.name)
        print(key)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
