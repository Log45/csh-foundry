"""Current platform membership/RBAC and SQL-expressible restrictive ABAC.

The transaction security lock is held until the governed transaction commits. No token
role claims, authorization-result cache, executable policies or Python row filtering.
"""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.db.models import (
    AuthorizationAudit,
    ExternalIdentity,
    Membership,
    Object,
    PlatformPrincipal,
    PolicyBinding,
    Role,
    RoleAssignment,
    SecurityPolicy,
    SecurityState,
    WorkerDelegation,
)
from ontology_platform.errors import ApplicationError
from ontology_platform.queries.ast import All, AnyOf, Filter, Negation, Predicate
from ontology_platform.security.contracts import AuthorizationDecision, PolicyInput
from ontology_platform.security.interfaces import Principal
from ontology_platform.security.query import QueryGrant


def denied() -> ApplicationError:
    return ApplicationError("forbidden", "Operation is not authorized", 403)


@dataclass
class SecuritySnapshot:
    tenant_id: UUID | None = None
    revision: int = 0
    members: dict[tuple[str, str | None, str | None, str, str], Membership] = field(
        default_factory=dict
    )
    permissions: dict[str, set[str]] = field(default_factory=dict)
    grants: dict[tuple[str, str, str], QueryGrant] = field(default_factory=dict)
    policies: list[SecurityPolicy] | None = None
    principals: dict[str, PlatformPrincipal] = field(default_factory=dict)
    pending_audit: list[AuthorizationAudit] = field(default_factory=list)
    delegations: dict[tuple[str, str, str, str], list[WorkerDelegation]] = field(
        default_factory=dict
    )


class PlatformAuthorizer:
    def __init__(self, sessions: sessionmaker[Session], *, test_mode: bool = False):
        self.sessions = sessions
        self.test_mode = test_mode
        self.current: ContextVar[Session | None] = ContextVar("security_session", default=None)
        self.snapshot: ContextVar[SecuritySnapshot | None] = ContextVar(
            "security_snapshot", default=None
        )

    @contextmanager
    def security_context(self, session: Session, p: Principal) -> Iterator[None]:
        current = self.current.get()
        if current is not None and current is not session:
            raise RuntimeError("Authorization session mismatch")
        if current is not None:
            snapshot = self.snapshot.get()
            if snapshot is None or snapshot.tenant_id != p.tenant_id:
                raise denied()
            yield
            return
        token = self.current.set(session)
        snapshot_token = self.snapshot.set(SecuritySnapshot()) if current is None else None
        try:
            # Lock BEFORE reading membership/policies. Admin uses FOR UPDATE on the same row.
            state = session.scalar(
                select(SecurityState)
                .where(SecurityState.tenant_id == p.tenant_id)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
            snapshot = self.snapshot.get()
            assert snapshot is not None
            snapshot.revision = state.revision if state is not None else 0
            snapshot.tenant_id = p.tenant_id
            yield
        finally:
            try:
                snapshot = self.snapshot.get()
                if snapshot is not None:
                    self.flush_audit(snapshot)
            finally:
                self.current.reset(token)
                if snapshot_token is not None:
                    self.snapshot.reset(snapshot_token)

    def identity(self, session: Session, p: Principal) -> Membership:
        if p.authentication_method not in (
            {"oidc", "delegated", "test"} if self.test_mode else {"oidc", "delegated"}
        ):
            raise denied()
        if p.expires_at is None or p.expires_at <= datetime.now(UTC):
            raise denied()
        snapshot = self.snapshot.get()
        cache_key = (
            p.principal_id,
            p.identity_provider,
            p.external_subject,
            p.authentication_method,
            p.principal_type,
        )
        if snapshot is not None and snapshot.tenant_id != p.tenant_id:
            raise denied()
        if snapshot is not None and cache_key in snapshot.members:
            return snapshot.members[cache_key]
        row = session.scalar(
            select(PlatformPrincipal)
            .where(PlatformPrincipal.id == p.principal_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        member = session.get(Membership, (p.tenant_id, p.principal_id), populate_existing=True)
        if (
            row is None
            or not row.enabled
            or row.principal_type != p.principal_type
            or member is None
            or not member.enabled
        ):
            raise denied()
        if p.authentication_method != "delegated":
            binding = session.get(ExternalIdentity, (p.identity_provider, p.external_subject))
            if binding is None or binding.principal_id != p.principal_id:
                raise denied()
        if snapshot is not None:
            snapshot.members[cache_key] = member
            snapshot.principals[p.principal_id] = row
        return member

    def permissions(self, session: Session, p: Principal) -> set[str]:
        snapshot = self.snapshot.get()
        if snapshot is not None and p.principal_id in snapshot.permissions:
            return snapshot.permissions[p.principal_id]
        rows = session.scalars(
            select(Role)
            .join(
                RoleAssignment,
                (Role.tenant_id == RoleAssignment.tenant_id) & (Role.id == RoleAssignment.role_id),
            )
            .where(
                RoleAssignment.tenant_id == p.tenant_id,
                RoleAssignment.principal_id == p.principal_id,
            )
            .limit(101)
        )
        roles = list(rows)
        if len(roles) > 100:
            raise ApplicationError("policy_limit", "Too many assigned roles", 503)
        permissions = {permission for row in roles for permission in row.permissions}
        if snapshot is not None:
            snapshot.permissions[p.principal_id] = permissions
        return permissions

    def delegation(self, session: Session, p: Principal, resource: str) -> Principal | None:
        if p.authentication_method != "delegated":
            return None
        if not p.actor_id or not p.delegation_kind or not p.delegation_ontology:
            raise denied()
        # Exact registered ontology resource prefix, never an incoming token's authority.
        snapshot = self.snapshot.get()
        cache_key = (p.principal_id, p.actor_id, p.delegation_kind, p.delegation_ontology)
        rows = snapshot.delegations.get(cache_key) if snapshot is not None else None
        if rows is None:
            rows = list(
                session.scalars(
                    select(WorkerDelegation).where(
                        WorkerDelegation.tenant_id == p.tenant_id,
                        WorkerDelegation.worker_id == p.actor_id,
                        WorkerDelegation.principal_id == p.principal_id,
                        WorkerDelegation.kind == p.delegation_kind,
                        WorkerDelegation.ontology_id == p.delegation_ontology,
                    )
                )
            )
            if snapshot is not None:
                snapshot.delegations[cache_key] = rows
        if not any(
            d.enabled
            and d.expires_at > datetime.now(UTC)
            and (
                resource == f"{p.tenant_id}/{d.ontology_id}"
                or resource.startswith(f"{p.tenant_id}/{d.ontology_id}/")
            )
            for d in rows
        ):
            raise denied()
        worker_row = session.get(PlatformPrincipal, p.actor_id)
        if worker_row is None or worker_row.principal_type != "service":
            raise denied()
        worker = p.model_copy(update={"principal_id": p.actor_id, "principal_type": "service"})
        self.identity(session, worker)
        if "worker:delegate" not in self.permissions(session, worker):
            raise denied()
        return worker

    def audit(
        self,
        p: Principal,
        operation: str,
        resource: str,
        allowed: bool,
        category: str,
        revision: int,
    ) -> UUID:
        key = uuid4()
        row = AuthorizationAudit(
            id=key,
            tenant_id=p.tenant_id,
            principal_id=p.principal_id,
            actor_id=p.actor_id,
            operation=operation[:200],
            resource_hash=hashlib.sha256(resource.encode()).hexdigest(),
            allowed=allowed,
            category=category,
            policy_version=revision,
        )
        snapshot = self.snapshot.get()
        if snapshot is None:
            with self.sessions.begin() as audit_session:
                audit_session.add(row)
        else:
            snapshot.pending_audit.append(row)
            # Independent bounded batches retain decision evidence on business rollback.
            # A denial flushes immediately; success/failure scope exit flushes the remainder.
            if not allowed or len(snapshot.pending_audit) >= 256:
                self.flush_audit(snapshot)
        return key

    def flush_audit(self, snapshot: SecuritySnapshot) -> None:
        if not snapshot.pending_audit:
            return
        rows, snapshot.pending_audit = snapshot.pending_audit, []
        with self.sessions.begin() as audit_session:
            audit_session.add_all(rows)

    def policy_denial(self, p: Principal, operation: str, resource: str) -> None:
        snapshot = self.snapshot.get()
        self.audit(p, operation, resource, False, "policy", snapshot.revision if snapshot else 0)

    def authorize(self, p: Principal, operation: str, resource: str) -> AuthorizationDecision:
        session = self.current.get()
        if session is None:
            with self.sessions.begin() as owned, self.security_context(owned, p):
                return self.authorize(p, operation, resource)
        snapshot = self.snapshot.get()
        assert snapshot is not None
        revision = snapshot.revision
        category = "membership"
        allowed = False
        try:
            if not resource.startswith(f"{p.tenant_id}/"):
                raise denied()
            self.identity(session, p)
            category = "permission"
            if operation not in self.permissions(session, p):
                raise denied()
            category = "delegation"
            if p.authentication_method == "delegated":
                allowed_operations = {
                    "schema:read",
                    "object:read",
                    "object:query",
                    "property:read",
                    "link:read",
                    "source:read",
                    "mapping:read",
                    "source:use_binding",
                    "ingestion:history",
                }
                if p.delegation_kind == "semantic":
                    allowed_operations.update(
                        {"semantic:claim", "semantic:execute", "semantic:read", "semantic:export"}
                    )
                else:
                    allowed_operations.update(
                        {
                            "ingestion:claim",
                            "ingestion:execute",
                            "ingestion:cleanup",
                            "object:create",
                            "object:update",
                            "object:delete",
                            "object:link",
                            "property:update",
                            "link:create",
                            "link:delete",
                            "edit:initialize_source",
                            "edit:reconcile",
                            "edit:override",
                            "edit:resolve",
                        }
                    )
                if operation not in allowed_operations:
                    raise denied()
            worker = self.delegation(session, p, resource)
            if worker is not None and operation not in self.permissions(session, worker):
                raise denied()
            allowed, category = True, "allow"
        except ApplicationError:
            pass
        key = self.audit(p, operation, resource, allowed, category, revision)
        return AuthorizationDecision(
            allowed=allowed,
            permission=operation,
            policy_version=revision,
            category=category,
            audit_id=key,
        )

    def require(self, principal: Principal, operation: str, resource: str) -> None:
        if not self.authorize(principal, operation, resource).allowed:
            raise denied()
        # Property references in actions/semantic services must use the same visibility policy.
        if operation in {"property:read", "property:update"}:
            base, sep, prop = resource.rpartition("/properties/")
            bits = base.split("/", 4)
            if sep and len(bits) == 5 and bits[2] == "objects":
                grant = self.query_grant(principal, bits[1], bits[3])
                if grant.visible_properties is not None and prop not in grant.visible_properties:
                    self.audit(principal, operation, resource, False, "policy", int(grant.revision))
                    raise denied()

    def _grant(self, session: Session, p: Principal, ontology: str, type_id: str) -> QueryGrant:
        member = self.identity(session, p)
        snapshot = self.snapshot.get()
        cache_key = (p.principal_id, ontology, type_id)
        if snapshot is not None and cache_key in snapshot.grants:
            return snapshot.grants[cache_key]
        attributes = member.attributes | {"id": p.principal_id}
        visible: set[str] | None = None
        filters: list[Filter] = []
        no_rows = False
        if snapshot is not None and snapshot.policies is not None:
            policies = snapshot.policies
        else:
            policies = list(
                session.scalars(
                    select(SecurityPolicy)
                    .join(
                        PolicyBinding,
                        (SecurityPolicy.tenant_id == PolicyBinding.tenant_id)
                        & (SecurityPolicy.id == PolicyBinding.id)
                        & (SecurityPolicy.version == PolicyBinding.version),
                    )
                    .where(SecurityPolicy.tenant_id == p.tenant_id)
                    .limit(65)
                )
            )
            if snapshot is not None:
                snapshot.policies = policies
        if len(policies) > 64:
            raise ApplicationError("policy_limit", "Too many active policies", 503)
        for row in policies:
            policy = PolicyInput.model_validate(row.definition)
            if (
                not policy.enabled
                or (policy.ontology_id, policy.object_type) != (ontology, type_id)
                or policy.principal_id not in (None, p.principal_id)
            ):
                continue
            if policy.visible_properties is not None:
                visible = (
                    set(policy.visible_properties)
                    if visible is None
                    else visible & set(policy.visible_properties)
                )
            allows: list[Filter] = []
            denies: list[Filter] = []
            has_allow = False
            for rule in policy.rules:
                has_allow |= rule.effect == "allow"
                conditions: list[Filter] = []
                missing = False
                for condition in rule.conditions:
                    value = (
                        attributes.get(condition.principal_attribute)
                        if condition.principal_attribute
                        else condition.value
                    )
                    if value is None or (
                        condition.operator == "in"
                        and (not isinstance(value, list) or not 1 <= len(value) <= 16)
                    ):
                        missing = True
                        break
                    values = value if condition.operator == "in" else [value]
                    assert isinstance(values, list)
                    nodes = [
                        Predicate(property=condition.property, operator="eq", value=v)
                        for v in values
                        if v is not None
                    ]
                    if not nodes:
                        missing = True
                        break
                    conditions.append(
                        nodes[0] if len(nodes) == 1 else AnyOf.model_validate({"or": nodes})
                    )
                if missing:
                    if rule.effect == "deny":
                        no_rows = True
                    continue
                node = (
                    conditions[0]
                    if len(conditions) == 1
                    else All.model_validate({"and": conditions})
                )
                (allows if rule.effect == "allow" else denies).append(node)
            if has_allow:
                if not allows:
                    no_rows = True
                else:
                    filters.append(
                        allows[0] if len(allows) == 1 else AnyOf.model_validate({"or": allows})
                    )
            if denies:
                filters.append(
                    Negation.model_validate(
                        {
                            "not": denies[0]
                            if len(denies) == 1
                            else AnyOf.model_validate({"or": denies})
                        }
                    )
                )
        permissions = self.permissions(session, p)
        if "property:read" not in permissions:
            visible = set()
        if "object:read" not in permissions:
            no_rows = True
        revision = snapshot.revision if snapshot is not None else 0
        grant = QueryGrant(
            revision=str(revision),
            visible_properties=tuple(sorted(visible)) if visible is not None else None,
            allowed_object_ids=() if no_rows else None,
            filter=filters[0]
            if len(filters) == 1
            else All.model_validate({"and": filters})
            if filters
            else None,
        )
        if snapshot is not None:
            snapshot.grants[cache_key] = grant
        return grant

    def query_grant(self, p: Principal, ontology_id: str, object_type: str) -> QueryGrant:
        session = self.current.get()
        if session is None:
            with self.sessions.begin() as owned, self.security_context(owned, p):
                return self.query_grant(p, ontology_id, object_type)
        if p.authentication_method == "delegated" and ontology_id != p.delegation_ontology:
            raise denied()
        try:
            grant = self._grant(session, p, ontology_id, object_type)
        except (ValueError, TypeError) as exc:
            raise ApplicationError(
                "invalid_query_policy", "Policy cannot be evaluated", 503
            ) from exc
        worker = self.delegation(session, p, f"{p.tenant_id}/{ontology_id}")
        if worker is not None:
            other = self._grant(session, worker, ontology_id, object_type)
            visible = grant.visible_properties
            if other.visible_properties is not None:
                visible = (
                    other.visible_properties
                    if visible is None
                    else tuple(sorted(set(visible) & set(other.visible_properties)))
                )
            filters = [f for f in (grant.filter, other.filter) if f is not None]
            grant = grant.model_copy(
                update={
                    "visible_properties": visible,
                    "allowed_object_ids": ()
                    if () in (grant.allowed_object_ids, other.allowed_object_ids)
                    else None,
                    "filter": All.model_validate({"and": filters})
                    if len(filters) == 2
                    else filters[0]
                    if filters
                    else None,
                }
            )
        grant.check_complexity()
        return grant

    def object_check(
        self,
        p: Principal,
        operation: str,
        ontology: str,
        type_id: str,
        object_id: str,
        *,
        properties: dict[str, JsonValue] | None = None,
        changed: tuple[str, ...] = (),
    ) -> None:
        from ontology_platform.db.governance import GovernedService
        from ontology_platform.metadata.storage import active_definition
        from ontology_platform.queries.compiler import QueryCompiler

        session = self.current.get()
        if session is None:
            raise RuntimeError("Object authorization requires governed transaction")
        if p.authentication_method == "delegated" and ontology != p.delegation_ontology:
            raise denied()
        grant = self.query_grant(p, ontology, type_id)
        if grant.filter is None and grant.allowed_object_ids is None:
            if changed:
                self.require(
                    p, "property:update", f"{p.tenant_id}/{ontology}/objects/{type_id}/{object_id}"
                )
                if grant.visible_properties is not None and set(changed) - set(
                    grant.visible_properties
                ):
                    self.audit(
                        p, operation, f"{ontology}/{type_id}", False, "policy", int(grant.revision)
                    )
                    raise denied()
            return
        schema = active_definition(session, GovernedService.ontology(session, p, ontology))
        compiler = QueryCompiler(schema, p, self)
        compiler.grants[type_id] = grant
        resource = f"{p.tenant_id}/{ontology}/objects/{type_id}/{object_id}"
        if operation != "object:create":
            found = session.scalar(
                select(Object.object_id).where(
                    compiler.authorized(Object, type_id), Object.object_id == object_id
                )
            )
            if found is None and (grant.filter is not None or grant.allowed_object_ids is not None):
                self.audit(p, operation, resource, False, "policy", int(grant.revision))
                raise denied()
        if properties is not None:
            # Proposed-state evaluation uses PostgreSQL and the exact query compiler semantics.
            # A typed in-memory SQL VALUES relation avoids a second Python policy interpreter.
            from sqlalchemy import String, Uuid, column, values
            from sqlalchemy.dialects.postgresql import JSONB

            proposed = values(
                column("tenant_id", Uuid),
                column("ontology_id", String),
                column("object_type_id", String),
                column("object_id", String),
                column("schema_version", String),
                column("properties", JSONB),
                name="proposed",
            ).data([(p.tenant_id, ontology, type_id, object_id, schema.version, properties)])
            entity = proposed.c
            # Compiler accepts column namespaces as well as mapped aliases at runtime.
            predicate = compiler.authorized(entity, type_id)  # type: ignore[arg-type]
            if session.scalar(select(proposed.c.object_id).where(predicate)) is None:
                self.audit(p, operation, resource, False, "policy", int(grant.revision))
                raise denied()
        if changed:
            self.require(p, "property:update", resource)
            if grant.visible_properties is not None and set(changed) - set(
                grant.visible_properties
            ):
                self.audit(p, operation, resource, False, "policy", int(grant.revision))
                raise denied()
