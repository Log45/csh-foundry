"""Verify worker service credentials independently of per-job initiating subjects."""

from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.config import Settings
from ontology_platform.db.session import require_runtime_role
from ontology_platform.errors import ApplicationError
from ontology_platform.security.identity import resolve
from ontology_platform.security.interfaces import Authorizer, Principal
from ontology_platform.security.local import LocalAuthorizer
from ontology_platform.security.oidc import OIDCVerifier, https_url
from ontology_platform.security.service import PlatformAuthorizer


def worker_context(
    settings: Settings,
    sessions: sessionmaker[Session],
    kind: Literal["ingestion", "semantic", "outbox", "execution"],
    ontology: str,
) -> tuple[Principal, Authorizer]:
    if settings.environment == "production":
        require_runtime_role(sessions, allow_owner_runtime_role=settings.allow_owner_runtime_role)
    if settings.auth_mode in {"disabled", "local"} and settings.trusted_local_identity:
        return Principal(
            tenant_id=settings.local_tenant_id, principal_id=settings.local_principal_id
        ), LocalAuthorizer(settings)
    if (
        settings.auth_mode != "oidc"
        or (settings.worker_access_token is None and settings.worker_client_secret is None)
        or settings.worker_tenant_id is None
    ):
        raise ApplicationError(
            "worker_identity_required", "Verified service credentials and tenant required", 401
        )
    verifier = OIDCVerifier(
        settings.oidc_providers,
        ca_bundle=settings.oidc_ca_bundle,
        backchannel_port=settings.oidc_backchannel_port,
    )
    try:
        if settings.worker_client_secret is not None:
            provider = next(
                (p for p in settings.oidc_providers if p.id == settings.worker_provider_id), None
            )
            if provider is None or settings.worker_client_id not in provider.clients:
                raise ApplicationError(
                    "worker_identity_required", "Trusted worker provider required", 503
                )
            metadata = verifier.document(
                provider.issuer.rstrip("/") + "/.well-known/openid-configuration"
            )
            endpoint = metadata.get("token_endpoint")
            if metadata.get("issuer") != provider.issuer or not isinstance(endpoint, str):
                raise ApplicationError("worker_identity_required", "Invalid worker discovery", 503)
            https_url(endpoint)
            if urlsplit(endpoint).netloc != urlsplit(provider.issuer).netloc:
                raise ApplicationError("worker_identity_required", "Untrusted token endpoint", 503)
            response = verifier.document(
                endpoint,
                form={
                    "grant_type": "client_credentials",
                    "client_id": settings.worker_client_id,
                    "client_secret": settings.worker_client_secret.get_secret_value(),
                },
            )
            raw = response.get("access_token")
            if not isinstance(raw, str) or response.get("token_type", "").lower() != "bearer":
                raise ApplicationError(
                    "worker_identity_required", "Invalid worker token response", 503
                )
        else:
            assert settings.worker_access_token is not None
            raw = settings.worker_access_token.get_secret_value()
        provider, claims = verifier.verify(raw)
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
    auth.require(actor, f"{kind}:claim", f"{actor.tenant_id}/{ontology}")
    return actor, auth
