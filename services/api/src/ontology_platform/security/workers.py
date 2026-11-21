"""Discover due work across enabled tenant memberships using one verified service identity."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, TypeVar
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.config import Settings
from ontology_platform.db.models import (
    AutomationState,
    ExecutionJob,
    ExternalIdentity,
    GovernedDefinition,
    IngestionRun,
    JobExecutionGrant,
    LineagePending,
    Membership,
    OutboxEvent,
    PlatformPrincipal,
    Resource,
    Role,
    RoleAssignment,
    SemanticJob,
)
from ontology_platform.db.session import require_runtime_role
from ontology_platform.errors import ApplicationError
from ontology_platform.security.interfaces import Authorizer, Principal
from ontology_platform.security.local import LocalAuthorizer
from ontology_platform.security.oidc import OIDCVerifier, https_url
from ontology_platform.security.service import PlatformAuthorizer

Kind = Literal[
    "ingestion", "semantic", "outbox", "execution", "automation", "cleanup", "maintenance"
]
T = TypeVar("T")
PERMISSIONS = {
    "ingestion": ("ingestion:claim", "ingestion:execute", "worker:delegate"),
    "semantic": ("semantic:claim", "semantic:execute", "worker:delegate"),
    "outbox": ("outbox:deliver",),
    "execution": ("execution:claim", "worker:delegate"),
    "automation": ("automation:dispatch",),
    "cleanup": ("ingestion:cleanup",),
    "maintenance": ("execution:claim", "worker:delegate"),
}


def credentials(settings: Settings) -> tuple[str, str, datetime]:
    if settings.auth_mode != "oidc" or (
        settings.worker_access_token is None and settings.worker_client_secret is None
    ):
        raise ApplicationError(
            "worker_identity_required", "Verified service credentials required", 401
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
            token_type = response.get("token_type")
            if (
                not isinstance(raw, str)
                or not isinstance(token_type, str)
                or token_type.lower() != "bearer"
            ):
                raise ApplicationError(
                    "worker_identity_required", "Invalid worker token response", 503
                )
        else:
            assert settings.worker_access_token is not None
            raw = settings.worker_access_token.get_secret_value()
        provider, claims = verifier.verify(raw)
    finally:
        verifier.client.close()
    client = claims.get("azp", claims.get("client_id"))
    expires = datetime.fromtimestamp(claims["exp"], UTC)
    if (
        client != settings.worker_client_id
        or (settings.worker_provider_id and provider.id != settings.worker_provider_id)
        or (settings.worker_subject and claims["sub"] != settings.worker_subject)
        or expires <= datetime.now(UTC)
    ):
        raise ApplicationError("worker_identity_required", "Unexpected worker identity", 403)
    return provider.issuer, claims["sub"], expires


class WorkerPool:
    def __init__(self, settings: Settings, sessions: sessionmaker[Session]):
        if settings.environment == "production":
            require_runtime_role(
                sessions, allow_owner_runtime_role=settings.allow_owner_runtime_role
            )
        self.settings = settings
        self.sessions = sessions
        self.local = settings.auth_mode in {"disabled", "local"} and settings.trusted_local_identity
        self.authorizer: Authorizer = (
            LocalAuthorizer(settings) if self.local else PlatformAuthorizer(sessions)
        )
        self.credential = None if self.local else credentials(settings)
        if self.credential:
            with sessions.begin() as s:
                if settings.worker_auto_provision:
                    from ontology_platform.security.worker_registration import register

                    register(s, *self.credential[:2])
                else:
                    self.service_id(s, *self.credential[:2])

    @staticmethod
    def service_id(s: Session, issuer: str, subject: str) -> str | None:
        binding = s.get(ExternalIdentity, (issuer, subject))
        if binding is None:
            return None
        principal = s.get(PlatformPrincipal, binding.principal_id)
        if principal is None or principal.principal_type != "service" or not principal.enabled:
            raise ApplicationError(
                "worker_identity_required", "Enabled service identity required", 403
            )
        return principal.id

    def scopes(
        self, kind: Kind, ontology: str | None = None, *, cleanup_days: int | None = None
    ) -> list[tuple[Principal, str]]:
        # Select tenants before ontologies so adding more queues cannot multiply a tenant's weight.
        now = func.now()
        model: Any
        if kind == "maintenance":
            from ontology_platform.observability.index import INDEX_PREFIX

            model = LineagePending
            ready = or_(
                model.generation != model.indexed_generation,
                ~model.cursor.startswith(INDEX_PREFIX),
            )
        elif kind == "execution":
            model = ExecutionJob
            ready = or_(
                model.state == "QUEUED",
                model.state.in_(("ADMITTED", "RUNNING", "CANCELLING")) & (model.lease_until < now),
            )
        elif kind == "automation":
            model = AutomationState
            ready = model.enabled.is_(True) & or_(
                model.next_run_at <= now,
                (GovernedDefinition.specification["trigger"]["kind"].astext == "action.committed")
                & (model.checked_at <= now - timedelta(seconds=2)),
            )
        elif kind == "outbox":
            model = OutboxEvent
            ready = (model.next_attempt_at <= now) & model.status.in_(["PENDING", "CLAIMED"])
        elif kind == "cleanup":
            model = IngestionRun
            if cleanup_days is None:
                raise ValueError("Cleanup retention is required")
            ready = (
                (model.completed_at < now - timedelta(days=cleanup_days))
                & model.status.in_(["COMPLETED", "FAILED", "CANCELLED"])
                & model.staging_purged_at.is_(None)
            )
        else:
            model = IngestionRun if kind == "ingestion" else SemanticJob
            ready = or_(
                model.status == "PENDING", (model.status == "RUNNING") & (model.lease_until < now)
            )
        ontology_column = getattr(model, "ontology_id", None)
        criteria = [ready]
        if ontology and ontology_column is not None:
            criteria.append(ontology_column == ontology)
        if not self.local and self.settings.worker_auto_provision:
            self.enroll_queues(model, criteria, kind)
        with self.sessions() as s:
            if self.local:
                settings = self.settings
                criteria.append(model.tenant_id == settings.local_tenant_id)
            else:
                assert self.credential is not None
                issuer, subject, expires = self.credential
                principal_id = self.service_id(s, issuer, subject)
                if principal_id is None:
                    return []
                criteria.append(
                    exists().where(
                        Membership.tenant_id == model.tenant_id,
                        Membership.principal_id == principal_id,
                        Membership.enabled.is_(True),
                    )
                )
                for permission in PERMISSIONS[kind]:
                    criteria.append(
                        exists(
                            select(Role.id)
                            .join(
                                RoleAssignment,
                                (Role.tenant_id == RoleAssignment.tenant_id)
                                & (Role.id == RoleAssignment.role_id),
                            )
                            .where(
                                Role.tenant_id == model.tenant_id,
                                RoleAssignment.principal_id == principal_id,
                                Role.permissions.contains([permission]),
                            )
                        )
                    )
            query = select(model.tenant_id)
            if ontology_column is not None:
                query = query.add_columns(ontology_column)
            if kind == "automation":
                query = query.join(
                    GovernedDefinition,
                    (GovernedDefinition.tenant_id == AutomationState.tenant_id)
                    & (GovernedDefinition.resource_id == AutomationState.automation_id)
                    & (GovernedDefinition.id == AutomationState.definition_id),
                ).where(GovernedDefinition.specification["trigger"]["kind"].astext != "manual")
            queues = query.where(*criteria).distinct().subquery()
            if ontology_column is not None:
                ranked = select(
                    queues.c.tenant_id,
                    queues.c.ontology_id,
                    func.row_number()
                    .over(partition_by=queues.c.tenant_id, order_by=func.random())
                    .label("position"),
                ).subquery()
                candidates = select(ranked.c.tenant_id, ranked.c.ontology_id).order_by(
                    ranked.c.position, func.random()
                )
            else:
                candidates = select(queues.c.tenant_id).order_by(func.random())
            result = []
            for row in s.execute(candidates.limit(16)):
                tenant = row[0]
                if self.local:
                    actor = Principal(
                        tenant_id=tenant, principal_id=self.settings.local_principal_id
                    )
                else:
                    actor = Principal(
                        tenant_id=tenant,
                        principal_id=principal_id,
                        principal_type="service",
                        authentication_method="oidc",
                        identity_provider=issuer,
                        external_subject=subject,
                        expires_at=expires,
                    )
                result.append((actor, row[1] if ontology_column is not None else "projects"))
            return result

    def enroll_queues(self, model: Any, criteria: list[Any], kind: Kind) -> None:
        from ontology_platform.security.worker_registration import enroll

        assert self.credential is not None
        with self.sessions() as s:
            discovery = select(model.tenant_id)
            if kind == "automation":
                discovery = discovery.join(
                    GovernedDefinition,
                    (GovernedDefinition.tenant_id == AutomationState.tenant_id)
                    & (GovernedDefinition.resource_id == AutomationState.automation_id)
                    & (GovernedDefinition.id == AutomationState.definition_id),
                ).where(GovernedDefinition.specification["trigger"]["kind"].astext != "manual")
            tenants = list(
                s.scalars(
                    discovery.where(*criteria)
                    .group_by(model.tenant_id)
                    .order_by(func.random())
                    .limit(16)
                )
            )
        for tenant in tenants:
            with self.sessions.begin() as s:
                principal = self.service_id(s, *self.credential[:2])
                if principal is None:
                    return
                projects: set[UUID] = set()
                if kind == "execution":
                    grants = s.scalars(
                        select(JobExecutionGrant)
                        .join(
                            ExecutionJob,
                            (ExecutionJob.tenant_id == JobExecutionGrant.tenant_id)
                            & (ExecutionJob.id == JobExecutionGrant.execution_id),
                        )
                        .where(
                            JobExecutionGrant.tenant_id == tenant,
                            JobExecutionGrant.revoked_at.is_(None),
                            JobExecutionGrant.expires_at > func.now(),
                            *criteria,
                        )
                        .order_by(ExecutionJob.created_at, ExecutionJob.id)
                        .limit(100)
                    )
                    for grant in grants:
                        projects.update(UUID(value) for value in grant.projects)
                elif kind == "automation":
                    projects.update(
                        s.scalars(
                            select(Resource.project_id)
                            .join(
                                AutomationState,
                                (Resource.tenant_id == AutomationState.tenant_id)
                                & (Resource.id == AutomationState.automation_id),
                            )
                            .join(
                                GovernedDefinition,
                                (GovernedDefinition.tenant_id == AutomationState.tenant_id)
                                & (GovernedDefinition.resource_id == AutomationState.automation_id)
                                & (GovernedDefinition.id == AutomationState.definition_id),
                            )
                            .where(AutomationState.tenant_id == tenant, *criteria)
                            .limit(100)
                        )
                    )
                enroll(s, tenant, principal, projects)

    def run(
        self,
        kind: Kind,
        operation: Callable[[Principal, str], T | None],
        ontology: str | None = None,
        *,
        cleanup_days: int | None = None,
    ) -> Iterator[T]:
        for actor, scope in self.scopes(kind, ontology, cleanup_days=cleanup_days):
            try:
                result = operation(actor, scope)
            except ApplicationError as exc:
                if exc.status_code not in {403, 404}:
                    raise
                continue
            except DBAPIError as exc:
                if getattr(exc.orig, "sqlstate", None) not in {"55P03", "40P01"}:
                    raise
                continue
            if result is not None:
                yield result
