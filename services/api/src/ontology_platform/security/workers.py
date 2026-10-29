"""Server-configured worker credentials and explicit expiring delegation.

The returned principal keeps job ownership as the initiating subject. Every service decision
intersects that subject's current authority with the service account and delegation record.
"""

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.config import Settings
from ontology_platform.db.models import PlatformPrincipal
from ontology_platform.errors import ApplicationError
from ontology_platform.security.identity import resolve
from ontology_platform.security.interfaces import Authorizer, Principal
from ontology_platform.security.local import LocalAuthorizer
from ontology_platform.security.oidc import OIDCVerifier
from ontology_platform.security.service import PlatformAuthorizer


def worker_context(
    settings: Settings,
    sessions: sessionmaker[Session],
    kind: Literal["ingestion", "semantic", "outbox"],
    ontology: str,
) -> tuple[Principal, Authorizer]:
    if settings.auth_mode in {"disabled", "local"} and settings.trusted_local_identity:
        return Principal(
            tenant_id=settings.local_tenant_id, principal_id=settings.local_principal_id
        ), LocalAuthorizer(settings)
    if (
        settings.auth_mode != "oidc"
        or settings.worker_access_token is None
        or settings.worker_tenant_id is None
    ):
        raise ApplicationError(
            "worker_identity_required", "Verified service credentials and tenant required", 401
        )
    verifier = OIDCVerifier(settings.oidc_providers, ca_bundle=settings.oidc_ca_bundle)
    try:
        provider, claims = verifier.verify(settings.worker_access_token.get_secret_value())
    finally:
        verifier.client.close()
    actor = resolve(
        sessions,
        provider.issuer,
        claims["sub"],
        settings.worker_tenant_id,
        method="oidc",
        expires_at=datetime.fromtimestamp(claims["exp"], UTC),
    )
    if actor.principal_type != "service":
        raise ApplicationError(
            "worker_identity_required", "Worker must authenticate as a service", 403
        )
    auth = PlatformAuthorizer(sessions)
    if kind == "outbox":
        auth.require(actor, "outbox:deliver", f"{actor.tenant_id}/{ontology}")
        return actor, auth
    if not settings.worker_subject_id:
        raise ApplicationError(
            "delegation_required", "Configured initiating principal required", 403
        )
    with sessions() as session:
        row = session.get(PlatformPrincipal, settings.worker_subject_id)
        if row is None:
            raise ApplicationError("delegation_required", "Initiating principal unavailable", 403)
        p = actor.model_copy(
            update={
                "principal_id": row.id,
                "principal_type": row.principal_type,
                "authentication_method": "delegated",
                "actor_id": actor.principal_id,
                "delegation_kind": kind,
                "delegation_ontology": ontology,
            }
        )
    auth.require(p, f"{kind}:claim", f"{p.tenant_id}/{ontology}")
    return p, auth
