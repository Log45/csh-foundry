"""Platform-owned identity, permission and deterministic restrictive ABAC contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from ontology_platform.queries.ast import Name, QueryModel

PERMISSIONS = frozenset(
    """
tenant:read ontology:create ontology:read schema:write schema:read schema:validate
schema:publish schema:activate schema:export migration:plan migration:approve
object:create object:read object:update object:delete object:link object:query object:count
object:aggregate property:read property:update link:create link:read link:delete link:update
action:invoke action:history action:audit edit:initialize_source edit:reconcile edit:override
edit:resolve outbox:deliver source:create source:publish source:read source:use_binding
mapping:create mapping:publish mapping:read ingestion:execute ingestion:claim ingestion:history
ingestion:diagnostics ingestion:cancel ingestion:cleanup semantic:compile semantic:publish
semantic:export semantic:execute semantic:claim semantic:read semantic:history semantic:cancel
semantic:approve ontology:import ontology:import:read security:role:manage security:policy:manage
security:membership:manage security:audit:read security:read
security:delegation:manage worker:delegate
""".split()
)


class IdentityInput(QueryModel):
    issuer: str = Field(min_length=1, max_length=2048)
    subject: str = Field(min_length=1, max_length=512)
    principal_type: Literal["user", "service"] = "user"
    enabled: bool = True
    attributes: dict[Name, JsonValue] = Field(default_factory=dict, max_length=32)


class MembershipInput(QueryModel):
    enabled: bool
    attributes: dict[Name, JsonValue] = Field(default_factory=dict, max_length=32)


class RoleInput(QueryModel):
    id: Name
    permissions: tuple[Name, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def known(self) -> "RoleInput":
        if set(self.permissions) - PERMISSIONS:
            raise ValueError("Unknown permission")
        return self


class AssignmentInput(QueryModel):
    principal_id: str = Field(min_length=1, max_length=200)
    role_id: Name


class Condition(QueryModel):
    property: Name
    operator: Literal["eq", "in"] = "eq"
    principal_attribute: Name | None = None
    value: JsonValue = None

    @model_validator(mode="after")
    def operand(self) -> "Condition":
        if self.principal_attribute is None and self.value is None:
            raise ValueError("A nonnull constant or platform principal attribute is required")
        if self.principal_attribute is not None and self.value is not None:
            raise ValueError("Specify one operand source")
        return self


class Rule(QueryModel):
    effect: Literal["allow", "deny"]
    conditions: tuple[Condition, ...] = Field(min_length=1, max_length=8)


class PolicyInput(QueryModel):
    id: Name
    expected_version: int = Field(ge=0)
    enabled: bool = True
    ontology_id: Name
    object_type: Name
    principal_id: str | None = Field(default=None, min_length=1, max_length=200)
    visible_properties: tuple[Name, ...] | None = Field(default=None, max_length=64)
    rules: tuple[Rule, ...] = Field(default=(), max_length=8)


class DelegationInput(QueryModel):
    worker_id: str = Field(min_length=1, max_length=200)
    principal_id: str = Field(min_length=1, max_length=200)
    ontology_id: Name
    kind: Literal["ingestion", "semantic"]
    expires_at: datetime
    enabled: bool = True


class AuthorizationDecision(QueryModel):
    allowed: bool
    permission: str
    policy_version: int
    category: Literal[
        "allow", "unauthenticated", "membership", "permission", "policy", "delegation"
    ]
    audit_id: UUID


# Catalog only: services use permission names, never role names.
DEFAULT_ROLES: dict[str, tuple[str, ...]] = {
    "data-reader": (
        "tenant:read",
        "schema:read",
        "object:read",
        "property:read",
        "object:query",
        "object:aggregate",
        "object:count",
        "link:read",
    ),
    "data-editor": (
        "object:create",
        "object:update",
        "object:delete",
        "property:update",
        "object:link",
        "link:create",
        "link:delete",
    ),
    "ontology-editor": (
        "ontology:create",
        "ontology:read",
        "schema:read",
        "schema:write",
        "schema:validate",
        "schema:export",
        "migration:plan",
    ),
    "schema-publisher": ("schema:read", "schema:publish"),
    "schema-activator": (
        "schema:read",
        "schema:activate",
        "migration:approve",
        "object:read",
        "object:update",
        "property:read",
        "property:update",
        "link:read",
        "link:update",
    ),
    "action-executor": ("action:invoke", "action:history", "action:audit"),
    "ingestion-operator": tuple(
        sorted(
            p for p in PERMISSIONS if p.split(":")[0] in {"source", "mapping", "ingestion", "edit"}
        )
    ),
    "semantic-analyst": (
        "semantic:compile",
        "semantic:export",
        "semantic:execute",
        "semantic:read",
        "semantic:history",
        "semantic:cancel",
    ),
    "semantic-reviewer": ("semantic:read", "semantic:approve"),
    "ontology-importer": ("ontology:import", "ontology:import:read", "schema:export"),
    "security-administrator": tuple(sorted(p for p in PERMISSIONS if p.startswith("security:"))),
}
