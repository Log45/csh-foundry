from datetime import datetime
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Ontology(Base):
    __tablename__ = "ontologies"
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    namespace: Mapped[str] = mapped_column(Text)
    active_version: Mapped[str | None] = mapped_column(Text)
    active_status: Mapped[str] = mapped_column(String(20), default="PUBLISHED")
    __table_args__ = (
        CheckConstraint("active_status = 'PUBLISHED'", name="ck_active_published"),
        ForeignKeyConstraint(
            ["tenant_id", "id", "active_version", "active_status"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
                "ontology_versions.status",
            ],
            name="fk_active_version",
            use_alter=True,
        ),
    )


class Version(Base):
    __tablename__ = "ontology_versions"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    definition_json: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id"], ["ontologies.tenant_id", "ontologies.id"]
        ),
        UniqueConstraint("tenant_id", "ontology_id", "version", "status", name="uq_version_status"),
        CheckConstraint("status IN ('DRAFT', 'PUBLISHED')", name="ck_version_status"),
        CheckConstraint(
            "status != 'PUBLISHED' OR (published_at IS NOT NULL AND published_by IS NOT NULL)",
            name="ck_publication_actor",
        ),
    )


class ObjectType(Base):
    __tablename__ = "object_type_definitions"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    schema_version: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    definition: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "schema_version"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
            ],
        ),
    )


class LinkType(Base):
    __tablename__ = "link_type_definitions"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    schema_version: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_type: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str] = mapped_column(Text)
    cardinality: Mapped[str] = mapped_column(String(20))
    definition: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "schema_version", "source_type"],
            [
                "object_type_definitions.tenant_id",
                "object_type_definitions.ontology_id",
                "object_type_definitions.schema_version",
                "object_type_definitions.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "schema_version", "target_type"],
            [
                "object_type_definitions.tenant_id",
                "object_type_definitions.ontology_id",
                "object_type_definitions.schema_version",
                "object_type_definitions.id",
            ],
        ),
        UniqueConstraint(
            "tenant_id",
            "ontology_id",
            "schema_version",
            "id",
            "source_type",
            "target_type",
            name="uq_link_type_endpoints",
        ),
        CheckConstraint(
            "cardinality IN ('one_to_one','one_to_many','many_to_one','many_to_many')",
            name="ck_cardinality",
        ),
    )


class Object(Base):
    __tablename__ = "objects"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    object_type_id: Mapped[str] = mapped_column(Text, primary_key=True)
    object_id: Mapped[str] = mapped_column(Text, primary_key=True)
    schema_version: Mapped[str] = mapped_column(Text)
    properties: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "schema_version", "object_type_id"],
            [
                "object_type_definitions.tenant_id",
                "object_type_definitions.ontology_id",
                "object_type_definitions.schema_version",
                "object_type_definitions.id",
            ],
        ),
        CheckConstraint("version >= 1", name="ck_object_revision"),
        CheckConstraint("jsonb_typeof(properties) = 'object'", name="ck_object_properties"),
    )


class Link(Base):
    __tablename__ = "object_links"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    link_type_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_object_type_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_object_id: Mapped[str] = mapped_column(Text, primary_key=True)
    target_object_type_id: Mapped[str] = mapped_column(Text, primary_key=True)
    target_object_id: Mapped[str] = mapped_column(Text, primary_key=True)
    schema_version: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "tenant_id",
                "ontology_id",
                "schema_version",
                "link_type_id",
                "source_object_type_id",
                "target_object_type_id",
            ],
            [
                "link_type_definitions.tenant_id",
                "link_type_definitions.ontology_id",
                "link_type_definitions.schema_version",
                "link_type_definitions.id",
                "link_type_definitions.source_type",
                "link_type_definitions.target_type",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "source_object_type_id", "source_object_id"],
            [
                "objects.tenant_id",
                "objects.ontology_id",
                "objects.object_type_id",
                "objects.object_id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "target_object_type_id", "target_object_id"],
            [
                "objects.tenant_id",
                "objects.ontology_id",
                "objects.object_type_id",
                "objects.object_id",
            ],
        ),
        Index(
            "ix_link_target",
            "tenant_id",
            "ontology_id",
            "target_object_type_id",
            "target_object_id",
        ),
    )


class MigrationPlan(Base):
    __tablename__ = "schema_migration_plans"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    target_version: Mapped[str] = mapped_column(Text)
    base_version: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    updates: Mapped[list[JsonValue]] = mapped_column(JSONB)
    created_by: Mapped[str] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "target_version"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "base_version"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
            ],
        ),
    )


class Activation(Base):
    __tablename__ = "schema_activations"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    target_version: Mapped[str] = mapped_column(Text)
    previous_version: Mapped[str | None] = mapped_column(Text)
    plan_id: Mapped[UUID | None]
    actor: Mapped[str] = mapped_column(Text)
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "target_version"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "previous_version"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "plan_id"],
            [
                "schema_migration_plans.tenant_id",
                "schema_migration_plans.ontology_id",
                "schema_migration_plans.id",
            ],
        ),
        UniqueConstraint("tenant_id", "ontology_id", "plan_id", name="uq_activation_plan"),
    )


# Fixed-width keys avoid introducing B-tree key-size failures for valid long identities
# or future schemas with large values. Compiler equality always rechecks the exact values.
Index(
    "ix_objects_status_lookup",
    Object.tenant_id,
    func.md5(Object.ontology_id),
    func.md5(Object.object_type_id),
    func.md5(Object.properties.op("->>", return_type=Text())("operationalStatus")),
)

# The primary key uses the database collation; query cursors require bytewise ordering.
Index(
    "ix_objects_query_order",
    Object.tenant_id,
    Object.ontology_id,
    Object.object_type_id,
    Object.object_id.collate("C"),
)


class ActionExecution(Base):
    __tablename__ = "action_executions"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    action_id: Mapped[str] = mapped_column(Text)
    action_version: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(Text)
    principal_id: Mapped[str] = mapped_column(Text)
    key_hash: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="COMMITTED")
    result: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "schema_version"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
            ],
        ),
        UniqueConstraint(
            "tenant_id", "ontology_id", "principal_id", "key_hash", name="uq_action_key"
        ),
        CheckConstraint("status = 'COMMITTED'", name="ck_execution_status"),
        Index("ix_action_history", "tenant_id", "ontology_id", "created_at", "id"),
    )


class AuditEvent(Base):
    __tablename__ = "action_audit_events"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    execution_id: Mapped[UUID] = mapped_column()
    actor: Mapped[str] = mapped_column(Text)
    object_type_id: Mapped[str] = mapped_column(Text)
    object_id: Mapped[str] = mapped_column(Text)
    operation: Mapped[str] = mapped_column(String(30))
    details: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "execution_id"],
            [
                "action_executions.tenant_id",
                "action_executions.ontology_id",
                "action_executions.id",
            ],
        ),
        Index("ix_action_audit_object", "tenant_id", "ontology_id", "object_type_id", "object_id"),
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    execution_id: Mapped[UUID] = mapped_column()
    category: Mapped[str] = mapped_column(String(30), default="action.committed")
    payload: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    destination: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    claim_token: Mapped[UUID | None]
    last_error: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "execution_id"],
            [
                "action_executions.tenant_id",
                "action_executions.ontology_id",
                "action_executions.id",
            ],
        ),
        UniqueConstraint(
            "tenant_id", "ontology_id", "execution_id", "category", name="uq_action_event"
        ),
        CheckConstraint("category = 'action.committed'", name="ck_event_category"),
        CheckConstraint(
            "status IN ('PENDING','CLAIMED','DELIVERED','DEAD')", name="ck_event_status"
        ),
        CheckConstraint("attempts >= 0 AND attempts <= 5", name="ck_event_attempts"),
        Index("ix_outbox_pending", "status", "next_attempt_at"),
    )


class WebhookAttempt(Base):
    __tablename__ = "webhook_attempts"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    event_id: Mapped[UUID] = mapped_column()
    attempt: Mapped[int] = mapped_column()
    outcome: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "event_id"],
            ["outbox_events.tenant_id", "outbox_events.ontology_id", "outbox_events.id"],
        ),
        UniqueConstraint(
            "tenant_id", "ontology_id", "event_id", "attempt", name="uq_delivery_attempt"
        ),
    )


class EditOverlay(Base):
    __tablename__ = "edit_overlays"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    object_type_id: Mapped[str] = mapped_column(Text, primary_key=True)
    object_id: Mapped[str] = mapped_column(Text, primary_key=True)
    property_id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner: Mapped[str] = mapped_column(String(20))
    source: Mapped[str | None] = mapped_column(Text)
    value: Mapped[JsonValue] = mapped_column(JSONB(none_as_null=False), nullable=False)
    source_value: Mapped[JsonValue] = mapped_column(JSONB(none_as_null=False), nullable=False)
    updated_by: Mapped[str] = mapped_column(Text, server_default="legacy-unknown")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    revision: Mapped[int] = mapped_column(BigInteger)
    schema_version: Mapped[str] = mapped_column(Text)
    execution_id: Mapped[UUID | None]
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "schema_version"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "execution_id"],
            [
                "action_executions.tenant_id",
                "action_executions.ontology_id",
                "action_executions.id",
            ],
        ),
        CheckConstraint("owner IN ('source','pipeline','user','action')", name="ck_overlay_owner"),
    )


class ReconciliationConflict(Base):
    __tablename__ = "reconciliation_conflicts"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    object_type_id: Mapped[str] = mapped_column(Text)
    object_id: Mapped[str] = mapped_column(Text)
    property_id: Mapped[str] = mapped_column(Text)
    incoming: Mapped[JsonValue] = mapped_column(JSONB(none_as_null=False), nullable=False)
    source: Mapped[str] = mapped_column(Text)
    observed_revision: Mapped[int] = mapped_column(BigInteger)
    schema_version: Mapped[str] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "schema_version"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
            ],
        ),
        CheckConstraint(
            "status IN ('OPEN','PRESERVED','ACCEPTED')", name="ck_reconciliation_status"
        ),
        Index(
            "ix_reconciliation_object",
            "tenant_id",
            "ontology_id",
            "object_type_id",
            "object_id",
            "status",
        ),
    )
