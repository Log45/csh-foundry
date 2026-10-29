"""Tenant-scoped, transaction-governed security administration."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ontology_platform.db.models import (
    AuthorizationAudit,
    ExternalIdentity,
    Membership,
    PlatformPrincipal,
    PolicyBinding,
    Role,
    RoleAssignment,
    SecurityPolicy,
    SecurityState,
    WorkerDelegation,
)
from ontology_platform.errors import ApplicationError
from ontology_platform.security.contracts import (
    AssignmentInput,
    DelegationInput,
    IdentityInput,
    MembershipInput,
    PolicyInput,
    RoleInput,
)
from ontology_platform.security.interfaces import Principal
from ontology_platform.security.service import PlatformAuthorizer, denied


class SecurityAdministration:
    def __init__(self, authorizer: PlatformAuthorizer):
        self.auth = authorizer
        self.sessions = authorizer.sessions

    @contextmanager
    def operation(self, p: Principal, permission: str, *, write: bool = False) -> Iterator[Session]:
        try:
            with self.sessions.begin() as session:
                state = session.scalar(
                    select(SecurityState)
                    .where(SecurityState.tenant_id == p.tenant_id)
                    .with_for_update(read=not write)
                )
                if state is None:
                    raise denied()
                with self.auth.security_context(session, p):
                    self.auth.require(p, permission, f"{p.tenant_id}/security")
                    yield session
                    if write:
                        session.flush()
                        session.add(
                            AuthorizationAudit(
                                id=uuid4(),
                                tenant_id=p.tenant_id,
                                principal_id=p.principal_id,
                                actor_id=p.actor_id,
                                operation=permission + ":committed",
                                resource_hash=hashlib.sha256(
                                    f"{p.tenant_id}/security".encode()
                                ).hexdigest(),
                                allowed=True,
                                category="administration",
                                policy_version=session.scalar(
                                    select(SecurityState.revision).where(
                                        SecurityState.tenant_id == p.tenant_id
                                    )
                                )
                                or 0,
                            )
                        )
        except IntegrityError as exc:
            raise ApplicationError(
                "security_constraint", "Security persistence constraint conflict", 409
            ) from exc

    def identity(self, p: Principal, body: IdentityInput) -> str:
        with self.operation(p, "security:membership:manage", write=True) as session:
            # Stable issuer+subject identity; never rebind existing identities.
            binding = session.get(ExternalIdentity, (body.issuer, body.subject))
            if binding is None:
                key = str(uuid4())
                session.add(
                    PlatformPrincipal(id=key, principal_type=body.principal_type, enabled=True)
                )
                session.flush()
                session.add(
                    ExternalIdentity(issuer=body.issuer, subject=body.subject, principal_id=key)
                )
                session.flush()
            else:
                key = binding.principal_id
                principal = session.get(PlatformPrincipal, key)
                if principal is None or principal.principal_type != body.principal_type:
                    raise ApplicationError("identity_conflict", "Identity type cannot change", 409)
            row = session.get(Membership, (p.tenant_id, key))
            if row is not None:
                raise ApplicationError(
                    "membership_exists", "Use the membership update endpoint", 409
                )
            session.add(
                Membership(
                    tenant_id=p.tenant_id,
                    principal_id=key,
                    enabled=body.enabled,
                    attributes=body.attributes,
                )
            )
            return key

    def member(self, p: Principal, key: str, body: MembershipInput) -> None:
        with self.operation(p, "security:membership:manage", write=True) as session:
            row = session.get(Membership, (p.tenant_id, key))
            if row is None:
                raise denied()
            row.enabled, row.attributes = body.enabled, body.attributes

    def role(self, p: Principal, body: RoleInput) -> None:
        with self.operation(p, "security:role:manage", write=True) as session:
            if set(body.permissions) - self.auth.permissions(session, p):
                raise denied()
            if session.get(Role, (p.tenant_id, body.id)) is not None:
                raise ApplicationError(
                    "role_exists", "Role definitions are immutable; create a new role", 409
                )
            session.add(Role(tenant_id=p.tenant_id, id=body.id, permissions=list(body.permissions)))

    def assign(self, p: Principal, body: AssignmentInput, *, revoke: bool = False) -> None:
        with self.operation(p, "security:role:manage", write=True) as session:
            role = session.get(Role, (p.tenant_id, body.role_id))
            if role is None or set(role.permissions) - self.auth.permissions(session, p):
                raise denied()
            key = (p.tenant_id, body.principal_id, body.role_id)
            if revoke:
                session.execute(
                    delete(RoleAssignment).where(
                        RoleAssignment.tenant_id == p.tenant_id,
                        RoleAssignment.principal_id == body.principal_id,
                        RoleAssignment.role_id == body.role_id,
                    )
                )
            elif session.get(RoleAssignment, key) is None:
                session.add(
                    RoleAssignment(
                        tenant_id=p.tenant_id, principal_id=body.principal_id, role_id=body.role_id
                    )
                )

    def policy(self, p: Principal, body: PolicyInput) -> int:
        from ontology_platform.db.governance import GovernedService
        from ontology_platform.metadata.storage import active_definition
        from ontology_platform.objects.validation import object_type

        with self.operation(p, "security:policy:manage", write=True) as session:
            schema = active_definition(
                session, GovernedService.ontology(session, p, body.ontology_id)
            )
            typed = object_type(schema, body.object_type)
            props = {prop.id: prop for prop in typed.properties}
            if body.visible_properties is not None and set(body.visible_properties) - props.keys():
                raise ApplicationError("invalid_policy", "Unknown policy property", 422)
            for rule in body.rules:
                for condition in rule.conditions:
                    if condition.property not in props:
                        raise ApplicationError("invalid_policy", "Unknown policy property", 422)
                    if condition.principal_attribute is None:
                        value = condition.value
                        values = (
                            value
                            if condition.operator == "in" and isinstance(value, list)
                            else [value]
                        )
                        if condition.operator == "in" and (
                            not isinstance(value, list) or not 1 <= len(value) <= 16
                        ):
                            raise ApplicationError("invalid_policy", "IN requires 1–16 values", 422)
                        try:
                            for v in values:
                                if v is None:
                                    raise ValueError("Null predicate")
                                props[condition.property].validate_value(v)
                        except ValueError as exc:
                            raise ApplicationError(
                                "invalid_policy", "Policy operand type mismatch", 422
                            ) from exc
            binding = session.get(PolicyBinding, (p.tenant_id, body.id))
            old = binding.version if binding else 0
            if old != body.expected_version:
                raise ApplicationError("policy_version_conflict", "Policy version changed", 409)
            version = old + 1
            session.add(
                SecurityPolicy(
                    tenant_id=p.tenant_id,
                    id=body.id,
                    version=version,
                    definition=body.model_dump(mode="json"),
                )
            )
            session.flush()
            if binding:
                binding.version = version
            else:
                session.add(PolicyBinding(tenant_id=p.tenant_id, id=body.id, version=version))
            return version

    def delegate(self, p: Principal, body: DelegationInput) -> None:
        if body.expires_at.tzinfo is None or body.expires_at <= datetime.now(UTC):
            raise ApplicationError(
                "invalid_delegation", "Future timezone-aware expiry required", 422
            )
        with self.operation(p, "security:delegation:manage", write=True) as session:
            worker = session.get(PlatformPrincipal, body.worker_id)
            if worker is None or worker.principal_type != "service":
                raise denied()
            key = (p.tenant_id, body.worker_id, body.principal_id, body.ontology_id, body.kind)
            row = session.get(WorkerDelegation, key)
            if row is None:
                session.add(WorkerDelegation(tenant_id=p.tenant_id, **body.model_dump()))
            else:
                row.enabled, row.expires_at = body.enabled, body.expires_at

    def effective(self, p: Principal) -> dict[str, object]:
        with self.operation(p, "tenant:read") as session:
            state = session.get(SecurityState, p.tenant_id)
            assert state is not None
            return {
                "principal": p.model_dump(mode="json", exclude={"external_subject"}),
                "permissions": sorted(self.auth.permissions(session, p)),
                "policy_version": state.revision,
            }

    def roles(self, p: Principal, limit: int = 100, offset: int = 0) -> list[dict[str, object]]:
        with self.operation(p, "security:read") as session:
            return [
                {"id": r.id, "permissions": r.permissions}
                for r in session.scalars(
                    select(Role)
                    .where(Role.tenant_id == p.tenant_id)
                    .order_by(Role.id)
                    .limit(limit)
                    .offset(offset)
                )
            ]

    def audit(self, p: Principal, limit: int = 100, offset: int = 0) -> list[dict[str, object]]:
        with self.operation(p, "security:audit:read") as session:
            return [
                {
                    "id": str(r.id),
                    "principal_id": r.principal_id,
                    "actor_id": r.actor_id,
                    "operation": r.operation,
                    "resource_hash": r.resource_hash,
                    "allowed": r.allowed,
                    "category": r.category,
                    "policy_version": r.policy_version,
                    "created_at": r.created_at.isoformat(),
                }
                for r in session.scalars(
                    select(AuthorizationAudit)
                    .where(AuthorizationAudit.tenant_id == p.tenant_id)
                    .order_by(AuthorizationAudit.created_at.desc(), AuthorizationAudit.id)
                    .limit(limit)
                    .offset(offset)
                )
            ]

    def policies(self, p: Principal, limit: int, offset: int) -> list[dict[str, object]]:
        with self.operation(p, "security:read") as session:
            return [
                {"id": row.id, "version": row.version, "definition": row.definition}
                for row in session.scalars(
                    select(SecurityPolicy)
                    .where(SecurityPolicy.tenant_id == p.tenant_id)
                    .order_by(SecurityPolicy.id, SecurityPolicy.version.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ]

    def memberships(self, p: Principal, limit: int, offset: int) -> list[dict[str, object]]:
        with self.operation(p, "security:membership:manage") as session:
            return [
                {
                    "principal_id": row.principal_id,
                    "enabled": row.enabled,
                    "attributes": row.attributes,
                    "roles": list(
                        session.scalars(
                            select(RoleAssignment.role_id).where(
                                RoleAssignment.tenant_id == p.tenant_id,
                                RoleAssignment.principal_id == row.principal_id,
                            )
                        )
                    ),
                }
                for row in session.scalars(
                    select(Membership)
                    .where(Membership.tenant_id == p.tenant_id)
                    .order_by(Membership.principal_id)
                    .limit(limit)
                    .offset(offset)
                )
            ]
