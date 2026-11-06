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
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
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


class BrowserState(Base):
    __tablename__ = "browser_state"
    kind: Mapped[str] = mapped_column(String(10), primary_key=True)
    key: Mapped[str] = mapped_column(String(43), primary_key=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revision: Mapped[int] = mapped_column(default=1)
    __table_args__ = (
        CheckConstraint("kind IN ('login','session')", name="ck_browser_kind"),
        CheckConstraint("revision > 0", name="ck_browser_revision"),
        CheckConstraint("octet_length(ciphertext) <= 32768", name="ck_browser_size"),
    )


class RequestBudget(Base):
    __tablename__ = "request_budgets"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_minute: Mapped[int] = mapped_column(BigInteger)
    count: Mapped[int]
    __table_args__ = (CheckConstraint("count > 0", name="ck_budget_count"),)


class TenantResourceUsage(Base):
    __tablename__ = "tenant_resource_usage"
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    bytes_used: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (CheckConstraint("bytes_used >= 0", name="ck_usage_nonnegative"),)


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


class IngestionSource(Base):
    __tablename__ = "ingestion_sources"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    definition_json: Mapped[str] = mapped_column(Text)
    binding_revision: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id"], ["ontologies.tenant_id", "ontologies.id"]
        ),
        CheckConstraint("version >= 1", name="ck_ingestion_source_version"),
    )


class IngestionMapping(Base):
    __tablename__ = "ingestion_mappings"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(100))
    source_version: Mapped[int] = mapped_column()
    schema_version: Mapped[str] = mapped_column(Text)
    definition_json: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "source_id", "source_version"],
            [
                "ingestion_sources.tenant_id",
                "ingestion_sources.ontology_id",
                "ingestion_sources.id",
                "ingestion_sources.version",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "schema_version"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
            ],
        ),
        CheckConstraint("version >= 1", name="ck_ingestion_mapping_version"),
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    schema_version: Mapped[str] = mapped_column(Text)
    principal_id: Mapped[str] = mapped_column(Text)
    plan: Mapped[list[JsonValue]] = mapped_column(JSONB)
    policy: Mapped[str] = mapped_column(String(20))
    batch_size: Mapped[int] = mapped_column()
    key_hash: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    phase: Mapped[str] = mapped_column(String(20), default="STAGING")
    attempts: Mapped[int] = mapped_column(default=0)
    token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    mapping_cursor: Mapped[int] = mapped_column(default=0)
    row_cursor: Mapped[int] = mapped_column(default=0)
    checkpoint: Mapped[int] = mapped_column(default=0)
    staged: Mapped[int] = mapped_column(default=0)
    staged_bytes: Mapped[int] = mapped_column(default=0)
    processed: Mapped[int] = mapped_column(default=0)
    created: Mapped[int] = mapped_column(default=0)
    updated: Mapped[int] = mapped_column(default=0)
    links_created: Mapped[int] = mapped_column(default=0)
    rejected: Mapped[int] = mapped_column(default=0)
    observed: Mapped[dict[str, JsonValue]] = mapped_column(JSONB, default=dict)
    staging_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
            "policy IN ('reject_run','reject_batch','quarantine')", name="ck_ingestion_policy"
        ),
        CheckConstraint(
            "status != 'RUNNING' OR (token IS NOT NULL AND lease_until IS NOT NULL)",
            name="ck_ingestion_lease",
        ),
        CheckConstraint(
            "created >= 0 AND updated >= 0 AND rejected >= 0 "
            "AND processed >= 0 AND links_created >= 0",
            name="ck_ingestion_counts",
        ),
        UniqueConstraint(
            "tenant_id", "ontology_id", "principal_id", "key_hash", name="uq_ingestion_request"
        ),
        CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="ck_ingestion_state",
        ),
        CheckConstraint(
            "phase IN ('STAGING','VALIDATING','OBJECTS','LINKS','DONE')", name="ck_ingestion_phase"
        ),
        CheckConstraint(
            "attempts BETWEEN 0 AND 3 AND batch_size BETWEEN 1 AND 100", name="ck_ingestion_budget"
        ),
        CheckConstraint(
            "checkpoint >= 0 AND staged BETWEEN 0 AND 10000 "
            "AND staged_bytes BETWEEN 0 AND 16777216",
            name="ck_ingestion_checkpoint",
        ),
        Index("ix_ingestion_pending", "tenant_id", "status", "lease_until"),
        Index("ix_ingestion_history", "tenant_id", "ontology_id", "created_at", "id"),
    )


class IngestionStage(Base):
    __tablename__ = "ingestion_stage"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(primary_key=True)
    ordinal: Mapped[int] = mapped_column(primary_key=True)
    mapping_id: Mapped[str] = mapped_column(String(100))
    mapping_version: Mapped[int] = mapped_column()
    row_number: Mapped[int] = mapped_column()
    source_key: Mapped[str | None] = mapped_column(Text)
    object_type: Mapped[str] = mapped_column(Text)
    object_id: Mapped[str | None] = mapped_column(Text)
    properties: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    relationships: Mapped[list[JsonValue]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(20))
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "run_id"],
            ["ingestion_runs.tenant_id", "ingestion_runs.ontology_id", "ingestion_runs.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "mapping_id", "mapping_version"],
            [
                "ingestion_mappings.tenant_id",
                "ingestion_mappings.ontology_id",
                "ingestion_mappings.id",
                "ingestion_mappings.version",
            ],
        ),
        CheckConstraint(
            "state IN ('STAGED','INVALID','OBJECT_DONE','DONE','REJECTED','LINK_REJECTED')",
            name="ck_ingestion_stage_state",
        ),
        UniqueConstraint(
            "tenant_id",
            "ontology_id",
            "run_id",
            "mapping_id",
            "mapping_version",
            "row_number",
            name="uq_stage_location",
        ),
        Index(
            "ix_ingestion_stage_identity",
            "tenant_id",
            "ontology_id",
            "run_id",
            "object_type",
            "object_id",
        ),
    )


class IngestionDiagnostic(Base):
    __tablename__ = "ingestion_diagnostics"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column()
    mapping_id: Mapped[str | None] = mapped_column(String(100))
    mapping_version: Mapped[int | None]
    row_number: Mapped[int | None]
    code: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "mapping_id", "mapping_version"],
            [
                "ingestion_mappings.tenant_id",
                "ingestion_mappings.ontology_id",
                "ingestion_mappings.id",
                "ingestion_mappings.version",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "run_id"],
            ["ingestion_runs.tenant_id", "ingestion_runs.ontology_id", "ingestion_runs.id"],
        ),
        Index("ix_ingestion_diagnostics_run", "tenant_id", "ontology_id", "run_id"),
    )


class SourceObject(Base):
    __tablename__ = "source_object_identities"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    object_type: Mapped[str] = mapped_column(Text, primary_key=True)
    object_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_id: Mapped[str] = mapped_column(String(100))
    source_version: Mapped[int] = mapped_column()
    namespace: Mapped[str] = mapped_column(Text)
    source_key: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "source_id", "source_version"],
            [
                "ingestion_sources.tenant_id",
                "ingestion_sources.ontology_id",
                "ingestion_sources.id",
                "ingestion_sources.version",
            ],
        ),
        UniqueConstraint(
            "tenant_id",
            "ontology_id",
            "source_id",
            "namespace",
            "source_key",
            "object_type",
            name="uq_source_identity",
        ),
    )


class SourceLink(Base):
    __tablename__ = "source_link_state"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    object_type: Mapped[str] = mapped_column(Text, primary_key=True)
    object_id: Mapped[str] = mapped_column(Text, primary_key=True)
    link_type: Mapped[str] = mapped_column(Text, primary_key=True)
    target_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[str] = mapped_column(Text)
    managed: Mapped[bool] = mapped_column()
    edge_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "object_type", "object_id"],
            [
                "source_object_identities.tenant_id",
                "source_object_identities.ontology_id",
                "source_object_identities.object_type",
                "source_object_identities.object_id",
            ],
        ),
    )


class SemanticArtifact(Base):
    __tablename__ = "semantic_artifacts"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    schema_version: Mapped[str] = mapped_column(Text)
    principal_id: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    manifest_json: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    output_hash: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
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
            "tenant_id", "ontology_id", "principal_id", "fingerprint", name="uq_semantic_artifact"
        ),
        CheckConstraint("octet_length(content) <= 4194304", name="ck_semantic_artifact_size"),
        CheckConstraint(
            "kind IN"
            " ('ontology','shapes','asserted','validation','reasoning','derived','change','proof')",
            name="ck_semantic_artifact_kind",
        ),
    )


class SemanticJob(Base):
    __tablename__ = "semantic_jobs"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    schema_version: Mapped[str] = mapped_column(Text)
    principal_id: Mapped[str] = mapped_column(Text)
    primary_artifact: Mapped[UUID] = mapped_column()
    secondary_artifact: Mapped[UUID] = mapped_column()
    request_json: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    attempts: Mapped[int] = mapped_column(default=0)
    token: Mapped[UUID | None] = mapped_column()
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(100))
    outputs: Mapped[list[str]] = mapped_column(JSONB, default=list)
    history: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB, default=list)
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
            ["tenant_id", "ontology_id", "primary_artifact"],
            [
                "semantic_artifacts.tenant_id",
                "semantic_artifacts.ontology_id",
                "semantic_artifacts.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "secondary_artifact"],
            [
                "semantic_artifacts.tenant_id",
                "semantic_artifacts.ontology_id",
                "semantic_artifacts.id",
            ],
        ),
        UniqueConstraint(
            "tenant_id", "ontology_id", "principal_id", "fingerprint", name="uq_semantic_job"
        ),
        CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="ck_semantic_job_status",
        ),
        CheckConstraint("attempts BETWEEN 0 AND 3", name="ck_semantic_attempts"),
        CheckConstraint(
            "status != 'RUNNING' OR (token IS NOT NULL AND lease_until IS NOT NULL)",
            name="ck_semantic_lease",
        ),
        Index(
            "ix_semantic_claim", "tenant_id", "ontology_id", "principal_id", "status", "created_at"
        ),
    )


class DerivedFact(Base):
    __tablename__ = "semantic_derived_facts"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    set_id: Mapped[UUID] = mapped_column(primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject: Mapped[str] = mapped_column(Text)
    predicate: Mapped[str] = mapped_column(Text)
    object: Mapped[str] = mapped_column(Text)
    job_id: Mapped[UUID] = mapped_column()
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "set_id"],
            [
                "semantic_artifacts.tenant_id",
                "semantic_artifacts.ontology_id",
                "semantic_artifacts.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "job_id"],
            ["semantic_jobs.tenant_id", "semantic_jobs.ontology_id", "semantic_jobs.id"],
        ),
    )


class SemanticApproval(Base):
    __tablename__ = "semantic_approvals"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    set_id: Mapped[UUID] = mapped_column(primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    principal_id: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "set_id"],
            [
                "semantic_artifacts.tenant_id",
                "semantic_artifacts.ontology_id",
                "semantic_artifacts.id",
            ],
        ),
        CheckConstraint("state IN ('APPROVED','REJECTED')", name="ck_semantic_approval_state"),
    )


class OntologyImport(Base):
    __tablename__ = "ontology_imports"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    draft_version: Mapped[str | None] = mapped_column(Text)
    canonical_hash: Mapped[str | None] = mapped_column(String(64))
    bindings_json: Mapped[str] = mapped_column(Text)
    principal_id: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(20))
    original: Mapped[str] = mapped_column(Text)
    input_hash: Mapped[str] = mapped_column(String(64))
    graph: Mapped[str] = mapped_column(Text)
    request_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)
    diagnostics_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id"], ["ontologies.tenant_id", "ontologies.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "draft_version"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
            ],
        ),
        UniqueConstraint("tenant_id", "ontology_id", "draft_version", name="uq_import_draft"),
        CheckConstraint("octet_length(bindings_json) <= 262144", name="ck_import_bindings"),
        CheckConstraint("format IN ('turtle', 'rdfxml')", name="ck_import_format"),
        CheckConstraint("octet_length(original) <= 262144", name="ck_import_bytes"),
        CheckConstraint("octet_length(graph) <= 4194304", name="ck_import_graph"),
        CheckConstraint("octet_length(result_json) <= 262144", name="ck_import_result"),
        CheckConstraint("octet_length(request_json) <= 524288", name="ck_import_request"),
        CheckConstraint("octet_length(diagnostics_json) <= 4194304", name="ck_import_diagnostics"),
    )


class VocabularyBinding(Base):
    __tablename__ = "ontology_vocabulary_bindings"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    iri_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    iri: Mapped[str] = mapped_column(Text)
    target: Mapped[str] = mapped_column(Text)
    target_hash: Mapped[str] = mapped_column(String(64))
    import_id: Mapped[UUID] = mapped_column()
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "import_id"],
            ["ontology_imports.tenant_id", "ontology_imports.ontology_id", "ontology_imports.id"],
        ),
        UniqueConstraint("tenant_id", "ontology_id", "target_hash", name="uq_vocabulary_target"),
    )


class SecurityState(Base):
    __tablename__ = "security_state"
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger, server_default="1")


class PlatformPrincipal(Base):
    __tablename__ = "principals"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    principal_type: Mapped[str] = mapped_column(String(20))
    enabled: Mapped[bool] = mapped_column(default=True)
    __table_args__ = (
        CheckConstraint("principal_type IN ('user', 'service')", name="ck_principal_type"),
    )


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    issuer: Mapped[str] = mapped_column(String(2048), primary_key=True)
    subject: Mapped[str] = mapped_column(String(512), primary_key=True)
    principal_id: Mapped[str] = mapped_column(ForeignKey("principals.id"))


class Membership(Base):
    __tablename__ = "tenant_memberships"
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("security_state.tenant_id"), primary_key=True
    )
    principal_id: Mapped[str] = mapped_column(ForeignKey("principals.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    attributes: Mapped[dict[str, JsonValue]] = mapped_column(JSONB, default=dict)


class Role(Base):
    __tablename__ = "security_roles"
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("security_state.tenant_id"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    permissions: Mapped[list[str]] = mapped_column(JSONB)


class RoleAssignment(Base):
    __tablename__ = "role_assignments"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    role_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "principal_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.principal_id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "role_id"], ["security_roles.tenant_id", "security_roles.id"]
        ),
    )


class SecurityPolicy(Base):
    __tablename__ = "security_policy_versions"
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("security_state.tenant_id"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    definition: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    __table_args__ = (CheckConstraint("version > 0", name="ck_security_policy_version"),)


class PolicyBinding(Base):
    __tablename__ = "security_policy_bindings"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    version: Mapped[int]
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "id", "version"],
            [
                "security_policy_versions.tenant_id",
                "security_policy_versions.id",
                "security_policy_versions.version",
            ],
        ),
    )


class WorkerDelegation(Base):
    __tablename__ = "worker_delegations"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    ontology_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(default=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "principal_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.principal_id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "worker_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.principal_id"],
        ),
        CheckConstraint("kind IN ('ingestion', 'semantic')", name="ck_delegation_kind"),
    )


class AuthorizationAudit(Base):
    __tablename__ = "authorization_audit"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(index=True)
    principal_id: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str | None] = mapped_column(Text)
    operation: Mapped[str] = mapped_column(String(200))
    resource_hash: Mapped[str] = mapped_column(String(64))
    allowed: Mapped[bool]
    category: Mapped[str] = mapped_column(String(30))
    policy_version: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SchemaBranch(Base):
    __tablename__ = "ontology_branches"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    base_version: Mapped[str] = mapped_column(Text)
    base_status: Mapped[str] = mapped_column(String(20), default="PUBLISHED")
    base_hash: Mapped[str] = mapped_column(String(64))
    head_revision: Mapped[int] = mapped_column(BigInteger)
    head_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_by: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "base_version", "base_status"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
                "ontology_versions.status",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "id", "head_revision", "head_hash"],
            [
                "ontology_branch_revisions.tenant_id",
                "ontology_branch_revisions.ontology_id",
                "ontology_branch_revisions.branch_id",
                "ontology_branch_revisions.revision",
                "ontology_branch_revisions.content_hash",
            ],
            name="fk_branch_head",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint("tenant_id", "ontology_id", "name", name="uq_branch_name"),
        CheckConstraint("base_status = 'PUBLISHED'", name="ck_branch_published_base"),
        CheckConstraint("state IN ('ACTIVE','MERGED','ABANDONED')", name="ck_branch_state"),
        CheckConstraint("head_revision >= 1", name="ck_branch_revision"),
    )


class BranchRevision(Base):
    __tablename__ = "ontology_branch_revisions"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    branch_id: Mapped[UUID] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    parent_revision: Mapped[int | None] = mapped_column(BigInteger)
    content_hash: Mapped[str] = mapped_column(String(64))
    definition_json: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(String(500))
    provenance: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "branch_id"],
            [
                "ontology_branches.tenant_id",
                "ontology_branches.ontology_id",
                "ontology_branches.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "branch_id", "parent_revision"],
            [
                "ontology_branch_revisions.tenant_id",
                "ontology_branch_revisions.ontology_id",
                "ontology_branch_revisions.branch_id",
                "ontology_branch_revisions.revision",
            ],
        ),
        UniqueConstraint(
            "tenant_id",
            "ontology_id",
            "branch_id",
            "revision",
            "content_hash",
            name="uq_branch_revision_hash",
        ),
        CheckConstraint(
            "(revision = 1 AND parent_revision IS NULL) OR "
            "(revision > 1 AND parent_revision = revision - 1)",
            name="ck_branch_parent",
        ),
        CheckConstraint("octet_length(definition_json) <= 65536", name="ck_branch_snapshot_size"),
    )


class BranchMerge(Base):
    __tablename__ = "ontology_branch_merges"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    source_id: Mapped[UUID]
    source_revision: Mapped[int] = mapped_column(BigInteger)
    target_id: Mapped[UUID]
    target_revision: Mapped[int] = mapped_column(BigInteger)
    result_revision: Mapped[int] = mapped_column(BigInteger)
    provenance: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    author: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = tuple(
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", branch, rev],
            [
                "ontology_branch_revisions.tenant_id",
                "ontology_branch_revisions.ontology_id",
                "ontology_branch_revisions.branch_id",
                "ontology_branch_revisions.revision",
            ],
        )
        for branch, rev in (
            ("source_id", "source_revision"),
            ("target_id", "target_revision"),
            ("target_id", "result_revision"),
        )
    ) + (
        CheckConstraint("octet_length(provenance::text) <= 65536", name="ck_merge_provenance_size"),
    )


class SDKArtifact(Base):
    __tablename__ = "sdk_artifacts"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    schema_version: Mapped[str] = mapped_column(Text)
    schema_status: Mapped[str] = mapped_column(String(20), default="PUBLISHED")
    language: Mapped[str] = mapped_column(String(20))
    content_hash: Mapped[str] = mapped_column(String(64))
    manifest: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    files_json: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "schema_version", "schema_status"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
                "ontology_versions.status",
            ],
        ),
        UniqueConstraint("tenant_id", "ontology_id", "content_hash", name="uq_sdk_content"),
        CheckConstraint("schema_status = 'PUBLISHED'", name="ck_sdk_published"),
        CheckConstraint("language IN ('python','typescript')", name="ck_sdk_language"),
        CheckConstraint("octet_length(files_json) <= 8388608", name="ck_sdk_size"),
    )


class Project(Base):
    __tablename__ = "projects"
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    revision: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("state IN ('ACTIVE','ARCHIVED')", name="ck_project_state"),
        CheckConstraint("revision > 0", name="ck_project_revision"),
        Index(
            "uq_project_name",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("state = 'ACTIVE'"),
        ),
    )


class ProjectMember(Base):
    __tablename__ = "project_members"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(primary_key=True)
    principal_id: Mapped[str] = mapped_column(Text, primary_key=True)
    role: Mapped[str] = mapped_column(String(20))
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "project_id"], ["projects.tenant_id", "projects.id"]),
        CheckConstraint("role IN ('owner','editor','viewer')", name="ck_project_role"),
    )


class Folder(Base):
    __tablename__ = "project_folders"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    parent_id: Mapped[UUID | None]
    name: Mapped[str] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    revision: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "project_id"], ["projects.tenant_id", "projects.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "project_id", "parent_id"],
            ["project_folders.tenant_id", "project_folders.project_id", "project_folders.id"],
        ),
        CheckConstraint("id IS DISTINCT FROM parent_id", name="ck_folder_self"),
        CheckConstraint("state IN ('ACTIVE','ARCHIVED')", name="ck_folder_state"),
        CheckConstraint("revision > 0", name="ck_folder_revision"),
        Index(
            "uq_folder_name",
            "tenant_id",
            "project_id",
            "parent_id",
            "name",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("state = 'ACTIVE'"),
        ),
    )


class Resource(Base):
    __tablename__ = "platform_resources"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID]
    folder_id: Mapped[UUID | None]
    resource_type: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    revision: Mapped[int] = mapped_column(default=1)
    ontology_id: Mapped[str | None] = mapped_column(Text)
    schema_version: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "project_id"], ["projects.tenant_id", "projects.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "project_id", "folder_id"],
            ["project_folders.tenant_id", "project_folders.project_id", "project_folders.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "schema_version"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
            ],
        ),
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "resource_type",
            "ontology_id",
            "schema_version",
            "entity_id",
            name="uq_resource_authority",
        ),
        CheckConstraint(
            "resource_type IN ('ONTOLOGY_OBJECT_TYPE','ONTOLOGY_LINK_TYPE',"
            "'ONTOLOGY_ACTION','ONTOLOGY_VERSION','ARTIFACT','DATASET','PIPELINE','MAPPING',"
            "'MEDIA_SET','FUNCTION','AUTOMATION','APPLICATION')",
            name="ck_resource_type",
        ),
        CheckConstraint(
            "(resource_type IN ('ARTIFACT','DATASET','PIPELINE','MAPPING',"
            "'MEDIA_SET','FUNCTION','AUTOMATION','APPLICATION') AND ontology_id IS NULL "
            "AND schema_version IS NULL "
            "AND entity_id IS NULL) OR (resource_type NOT IN "
            "('ARTIFACT','DATASET','PIPELINE','MAPPING','MEDIA_SET',"
            "'FUNCTION','AUTOMATION','APPLICATION') "
            "AND ontology_id IS NOT NULL "
            "AND schema_version IS NOT NULL AND entity_id IS NOT NULL)",
            name="ck_resource_authority_kind",
        ),
        CheckConstraint("state IN ('ACTIVE','ARCHIVED')", name="ck_resource_state"),
        CheckConstraint("revision > 0", name="ck_resource_revision"),
        Index(
            "uq_resource_name",
            "tenant_id",
            "project_id",
            "folder_id",
            "name",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("state = 'ACTIVE'"),
        ),
    )


class ResourceShare(Base):
    __tablename__ = "resource_shares"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    resource_id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(primary_key=True)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "resource_id"], ["platform_resources.tenant_id", "platform_resources.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "project_id"], ["projects.tenant_id", "projects.id"]),
    )


class ArtifactVersion(Base):
    __tablename__ = "artifact_versions"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    artifact_id: Mapped[UUID] = mapped_column(primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    sequence: Mapped[int]
    backend: Mapped[str] = mapped_column(String(20))
    bucket: Mapped[str] = mapped_column(Text)
    object_key: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(BigInteger)
    checksum: Mapped[str] = mapped_column(String(64))
    media_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    filename: Mapped[str] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(20), default="PENDING")
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provenance: Mapped[dict[str, JsonValue]] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "artifact_id"], ["platform_resources.tenant_id", "platform_resources.id"]
        ),
        UniqueConstraint("tenant_id", "artifact_id", "sequence", name="uq_artifact_sequence"),
        UniqueConstraint("backend", "bucket", "object_key", name="uq_artifact_object"),
        CheckConstraint("sequence > 0 AND size >= 0", name="ck_artifact_size_sequence"),
        CheckConstraint("checksum ~ '^[a-f0-9]{64}$'", name="ck_artifact_checksum"),
        CheckConstraint(
            "state IN ('PENDING','COMMITTED','FAILED','DELETED')", name="ck_artifact_state"
        ),
        CheckConstraint(
            "(state = 'COMMITTED') = (committed_at IS NOT NULL)", name="ck_artifact_commit"
        ),
    )


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    artifact_id: Mapped[UUID] = mapped_column(primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    format: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20), default="PENDING")
    result: Mapped[dict[str, JsonValue]] = mapped_column(JSONB, default=dict)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "artifact_id", "id"],
            [
                "artifact_versions.tenant_id",
                "artifact_versions.artifact_id",
                "artifact_versions.id",
            ],
        ),
        CheckConstraint("format IN ('csv','json','ndjson','parquet')", name="ck_dataset_format"),
        CheckConstraint("state IN ('PENDING','COMMITTED','FAILED')", name="ck_dataset_state"),
        CheckConstraint(
            "(state IN ('COMMITTED','FAILED')) = (finalized_at IS NOT NULL)",
            name="ck_dataset_commit",
        ),
    )


class PipelineDefinition(Base):
    __tablename__ = "pipeline_definitions"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    pipeline_id: Mapped[UUID] = mapped_column(primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    sequence: Mapped[int]
    specification: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "pipeline_id"], ["platform_resources.tenant_id", "platform_resources.id"]
        ),
        UniqueConstraint("tenant_id", "pipeline_id", "sequence", name="uq_pipeline_sequence"),
        CheckConstraint("sequence > 0", name="ck_pipeline_sequence"),
    )


class PipelineDraft(Base):
    __tablename__ = "pipeline_drafts"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    pipeline_id: Mapped[UUID] = mapped_column(primary_key=True)
    actor_id: Mapped[str] = mapped_column(Text, primary_key=True)
    revision: Mapped[int]
    graph: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "pipeline_id"], ["platform_resources.tenant_id", "platform_resources.id"]
        ),
        CheckConstraint("revision > 0", name="ck_pipeline_draft_revision"),
        CheckConstraint("octet_length(graph::text) <= 524288", name="ck_pipeline_draft_bytes"),
    )


class PipelineGraph(Base):
    __tablename__ = "pipeline_graphs"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    pipeline_id: Mapped[UUID] = mapped_column(primary_key=True)
    definition_id: Mapped[UUID] = mapped_column(primary_key=True)
    graph: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    semantic_digest: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "pipeline_id", "definition_id"],
            [
                "pipeline_definitions.tenant_id",
                "pipeline_definitions.pipeline_id",
                "pipeline_definitions.id",
            ],
        ),
        CheckConstraint("octet_length(graph::text) <= 524288", name="ck_pipeline_graph_bytes"),
    )


class ExecutionJob(Base):
    __tablename__ = "execution_jobs"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    resource_id: Mapped[UUID]
    project_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(20))
    definition_id: Mapped[UUID | None]
    mapping_definition_id: Mapped[UUID | None]
    validation_version_id: Mapped[UUID | None]
    output_dataset_id: Mapped[UUID | None]
    output_version_id: Mapped[UUID | None]
    request: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    principal: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    limits: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(20), default="QUEUED")
    attempts: Mapped[int] = mapped_column(default=0)
    token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(100))
    metrics: Mapped[dict[str, JsonValue]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    admitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "resource_id"], ["platform_resources.tenant_id", "platform_resources.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "project_id"], ["projects.tenant_id", "projects.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "resource_id", "definition_id"],
            [
                "pipeline_definitions.tenant_id",
                "pipeline_definitions.pipeline_id",
                "pipeline_definitions.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "resource_id", "validation_version_id"],
            ["dataset_versions.tenant_id", "dataset_versions.artifact_id", "dataset_versions.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "output_dataset_id", "output_version_id"],
            ["dataset_versions.tenant_id", "dataset_versions.artifact_id", "dataset_versions.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "resource_id", "mapping_definition_id"],
            [
                "mapping_definitions.tenant_id",
                "mapping_definitions.mapping_id",
                "mapping_definitions.id",
            ],
        ),
        UniqueConstraint(
            "tenant_id", "resource_id", "validation_version_id", name="uq_dataset_validation_job"
        ),
        UniqueConstraint(
            "tenant_id", "output_dataset_id", "output_version_id", name="uq_run_output"
        ),
        CheckConstraint(
            "kind IN ('VALIDATION','PIPELINE','MATERIALIZATION','FUNCTION')",
            name="ck_execution_kind",
        ),
        CheckConstraint(
            "state IN ('QUEUED','ADMITTED','RUNNING','CANCELLING',"
            "'SUCCEEDED','FAILED','CANCELLED')",
            name="ck_execution_state",
        ),
        CheckConstraint("attempts >= 0", name="ck_execution_attempts"),
        CheckConstraint(
            "(state IN ('ADMITTED','RUNNING','CANCELLING')) = "
            "(token IS NOT NULL AND lease_until IS NOT NULL)",
            name="ck_execution_lease",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "output_dataset_id"],
            ["platform_resources.tenant_id", "platform_resources.id"],
        ),
        CheckConstraint(
            "(state IN ('SUCCEEDED','FAILED','CANCELLED')) = (completed_at IS NOT NULL)",
            name="ck_execution_completed",
        ),
        CheckConstraint(
            "(kind = 'VALIDATION' AND validation_version_id IS NOT NULL "
            "AND definition_id IS NULL AND mapping_definition_id IS NULL "
            "AND output_dataset_id IS NULL) OR "
            "(kind = 'PIPELINE' AND definition_id IS NOT NULL AND "
            "validation_version_id IS NULL AND mapping_definition_id IS NULL "
            "AND (output_dataset_id IS NOT NULL OR "
            "coalesce(request->>'format_version','')='2')) OR "
            "(kind = 'MATERIALIZATION' AND mapping_definition_id IS NOT NULL "
            "AND definition_id IS NULL "
            "AND validation_version_id IS NULL AND output_dataset_id IS NULL) OR "
            "(kind = 'FUNCTION' AND definition_id IS NULL AND mapping_definition_id IS NULL "
            "AND validation_version_id IS NULL AND output_dataset_id IS NULL)",
            name="ck_execution_contract",
        ),
        Index("ix_execution_queue", "state", "created_at"),
    )


class ExecutionInput(Base):
    __tablename__ = "execution_inputs"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), primary_key=True)
    dataset_id: Mapped[UUID]
    version_id: Mapped[UUID]
    checksum: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "job_id"], ["execution_jobs.tenant_id", "execution_jobs.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "dataset_id", "version_id"],
            ["dataset_versions.tenant_id", "dataset_versions.artifact_id", "dataset_versions.id"],
        ),
    )


class MappingDefinition(Base):
    __tablename__ = "mapping_definitions"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    mapping_id: Mapped[UUID] = mapped_column(primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    sequence: Mapped[int]
    target_resource_id: Mapped[UUID]
    ontology_id: Mapped[str] = mapped_column(Text)
    schema_version: Mapped[str] = mapped_column(Text)
    specification: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "mapping_id"], ["platform_resources.tenant_id", "platform_resources.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "target_resource_id"],
            ["platform_resources.tenant_id", "platform_resources.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id", "schema_version"],
            [
                "ontology_versions.tenant_id",
                "ontology_versions.ontology_id",
                "ontology_versions.version",
            ],
        ),
        UniqueConstraint("tenant_id", "mapping_id", "sequence", name="uq_mapping_sequence"),
        CheckConstraint("sequence > 0", name="ck_mapping_sequence"),
    )


class MappingOwnership(Base):
    __tablename__ = "mapping_ownership"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    ontology_id: Mapped[str] = mapped_column(Text, primary_key=True)
    object_type: Mapped[str] = mapped_column(Text, primary_key=True)
    object_id: Mapped[str] = mapped_column(Text, primary_key=True)
    mapping_id: Mapped[UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "mapping_id"], ["platform_resources.tenant_id", "platform_resources.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "ontology_id"], ["ontologies.tenant_id", "ontologies.id"]
        ),
    )


class MaterializationRecord(Base):
    __tablename__ = "materialization_records"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column(primary_key=True)
    target_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    target: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    source_record: Mapped[int] = mapped_column(BigInteger)
    operation: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "run_id"], ["execution_jobs.tenant_id", "execution_jobs.id"]
        ),
        CheckConstraint(
            "operation IN ('created','updated','preserved','observed')",
            name="ck_materialization_operation",
        ),
        CheckConstraint("source_record > 0", name="ck_materialization_source"),
    )


class GovernedDefinition(Base):
    __tablename__ = "governed_definitions"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    resource_id: Mapped[UUID] = mapped_column(primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    target_resource_id: Mapped[UUID | None]
    target_definition_id: Mapped[UUID | None]
    event_resource_id: Mapped[UUID | None]
    sequence: Mapped[int]
    specification: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "resource_id"], ["platform_resources.tenant_id", "platform_resources.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "target_resource_id", "target_definition_id"],
            [
                "governed_definitions.tenant_id",
                "governed_definitions.resource_id",
                "governed_definitions.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_resource_id"],
            ["platform_resources.tenant_id", "platform_resources.id"],
        ),
        CheckConstraint(
            "(kind='AUTOMATION' AND target_resource_id IS NOT NULL AND "
            "target_definition_id IS NOT NULL) OR (kind<>'AUTOMATION' AND "
            "target_resource_id IS NULL AND target_definition_id IS NULL "
            "AND event_resource_id IS NULL)",
            name="ck_governed_target",
        ),
        UniqueConstraint("tenant_id", "resource_id", "sequence", name="uq_governed_sequence"),
        CheckConstraint("sequence > 0", name="ck_governed_sequence"),
        CheckConstraint("kind IN ('MEDIA_SET','FUNCTION','AUTOMATION')", name="ck_governed_kind"),
        CheckConstraint("octet_length(specification::text) <= 524288", name="ck_governed_bytes"),
    )


class MediaItem(Base):
    __tablename__ = "media_items"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    set_id: Mapped[UUID] = mapped_column(primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    artifact_id: Mapped[UUID]
    artifact_version_id: Mapped[UUID]
    media_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(BigInteger)
    checksum: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(Text)
    # Avoid Declarative's reserved metadata attribute.
    extracted: Mapped[dict[str, JsonValue]] = mapped_column("metadata", JSONB)
    preview_artifact_id: Mapped[UUID | None]
    preview_version_id: Mapped[UUID | None]
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "set_id"], ["platform_resources.tenant_id", "platform_resources.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "artifact_id", "artifact_version_id"],
            [
                "artifact_versions.tenant_id",
                "artifact_versions.artifact_id",
                "artifact_versions.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "preview_artifact_id", "preview_version_id"],
            [
                "artifact_versions.tenant_id",
                "artifact_versions.artifact_id",
                "artifact_versions.id",
            ],
        ),
        UniqueConstraint(
            "tenant_id", "set_id", "artifact_id", "artifact_version_id", name="uq_media_source"
        ),
        CheckConstraint("size >= 0", name="ck_media_size"),
        CheckConstraint(
            "media_type IN ('image/png','image/jpeg','audio/wav','video/mp4','application/pdf')",
            name="ck_media_type",
        ),
        CheckConstraint(
            "(preview_artifact_id IS NULL) = (preview_version_id IS NULL)", name="ck_media_preview"
        ),
    )


class MediaMembership(Base):
    __tablename__ = "media_memberships"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    set_id: Mapped[UUID] = mapped_column(primary_key=True)
    version_id: Mapped[UUID] = mapped_column(primary_key=True)
    item_id: Mapped[UUID] = mapped_column(primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "set_id", "version_id"],
            [
                "governed_definitions.tenant_id",
                "governed_definitions.resource_id",
                "governed_definitions.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "set_id", "item_id"],
            ["media_items.tenant_id", "media_items.set_id", "media_items.id"],
        ),
    )


class FunctionInvocation(Base):
    __tablename__ = "function_invocations"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    function_id: Mapped[UUID]
    definition_id: Mapped[UUID]
    key: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(Text)
    inputs: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "job_id"], ["execution_jobs.tenant_id", "execution_jobs.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "function_id", "definition_id"],
            [
                "governed_definitions.tenant_id",
                "governed_definitions.resource_id",
                "governed_definitions.id",
            ],
        ),
        UniqueConstraint("tenant_id", "function_id", "actor", "key", name="uq_function_key"),
        CheckConstraint("octet_length(inputs::text) <= 65536", name="ck_function_input_bytes"),
    )


class FunctionResult(Base):
    __tablename__ = "function_results"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    definition_id: Mapped[UUID]
    values: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["function_invocations.tenant_id", "function_invocations.job_id"],
        ),
        CheckConstraint("octet_length(values::text) <= 65536", name="ck_function_output_bytes"),
    )


class AutomationState(Base):
    __tablename__ = "automation_states"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    automation_id: Mapped[UUID] = mapped_column(primary_key=True)
    definition_id: Mapped[UUID]
    enabled: Mapped[bool] = mapped_column(default=False)
    activation_id: Mapped[UUID]
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_id: Mapped[UUID]
    owner: Mapped[str] = mapped_column(Text)
    principal: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    last_error: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "automation_id", "definition_id"],
            [
                "governed_definitions.tenant_id",
                "governed_definitions.resource_id",
                "governed_definitions.id",
            ],
        ),
        Index("ix_automation_due", "enabled", "next_run_at"),
    )


class AutomationReceipt(Base):
    __tablename__ = "automation_receipts"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    automation_id: Mapped[UUID] = mapped_column(primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    definition_id: Mapped[UUID]
    dedup_key: Mapped[str] = mapped_column(String(200))
    trigger_kind: Mapped[str] = mapped_column(String(30))
    trigger_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    job_id: Mapped[UUID | None]
    error: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "automation_id", "definition_id"],
            [
                "governed_definitions.tenant_id",
                "governed_definitions.resource_id",
                "governed_definitions.id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "job_id"], ["execution_jobs.tenant_id", "execution_jobs.id"]
        ),
        UniqueConstraint("tenant_id", "automation_id", "dedup_key", name="uq_automation_trigger"),
        CheckConstraint("(job_id IS NULL) <> (error IS NULL)", name="ck_automation_outcome"),
    )


class ApplicationDraft(Base):
    __tablename__ = "application_drafts"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    application_id: Mapped[UUID] = mapped_column(primary_key=True)
    actor_id: Mapped[str] = mapped_column(Text, primary_key=True)
    revision: Mapped[int]
    document: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "application_id"],
            ["platform_resources.tenant_id", "platform_resources.id"],
        ),
        CheckConstraint("revision > 0", name="ck_application_draft_revision"),
        CheckConstraint(
            "octet_length(document::text) <= 131072", name="ck_application_draft_bytes"
        ),
    )


class ApplicationVersion(Base):
    __tablename__ = "application_versions"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    application_id: Mapped[UUID] = mapped_column(primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    sequence: Mapped[int]
    format_version: Mapped[int]
    document: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    digest: Mapped[str] = mapped_column(String(64))
    manifest: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "application_id"],
            ["platform_resources.tenant_id", "platform_resources.id"],
        ),
        UniqueConstraint("tenant_id", "application_id", "sequence", name="uq_application_sequence"),
        UniqueConstraint("tenant_id", "application_id", "digest", name="uq_application_digest"),
        CheckConstraint("sequence > 0 AND format_version = 1", name="ck_application_version"),
        CheckConstraint(
            "octet_length(document::text) <= 131072", name="ck_application_version_bytes"
        ),
    )


class DAGRun(Base):
    __tablename__ = "dag_runs"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    plan_digest: Mapped[str] = mapped_column(String(64))
    plan: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(20), default="EXECUTING")
    commit_id: Mapped[UUID | None]
    cleaned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "job_id"], ["execution_jobs.tenant_id", "execution_jobs.id"]
        ),
        CheckConstraint(
            "state IN ('EXECUTING','PREPARING','PREPARED','COMMITTED','ABANDONED')",
            name="ck_dag_run_state",
        ),
        CheckConstraint("(state = 'COMMITTED') = (commit_id IS NOT NULL)", name="ck_dag_commit"),
        Index("ix_dag_cleanup", "cleaned_at"),
    )


class DAGNodeExecution(Base):
    __tablename__ = "dag_nodes"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    node_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    state: Mapped[str] = mapped_column(String(20), default="PENDING")
    attempt: Mapped[int] = mapped_column(default=0)
    token: Mapped[UUID | None]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_id: Mapped[UUID | None]
    result: Mapped[dict[str, JsonValue]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "job_id"], ["dag_runs.tenant_id", "dag_runs.job_id"]),
        CheckConstraint(
            "state IN ('PENDING','RUNNING','COMPLETED','FAILED')", name="ck_dag_node_state"
        ),
        CheckConstraint("attempt >= 0", name="ck_dag_node_attempt"),
    )


class DAGPreparedOutput(Base):
    __tablename__ = "dag_outputs"
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    output_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    dataset_id: Mapped[UUID]
    version_id: Mapped[UUID]
    state: Mapped[str] = mapped_column(String(20), default="PENDING")
    result: Mapped[dict[str, JsonValue]] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "job_id"], ["dag_runs.tenant_id", "dag_runs.job_id"]),
        UniqueConstraint("tenant_id", "dataset_id", "version_id", name="uq_dag_output_version"),
        UniqueConstraint("tenant_id", "job_id", "dataset_id", name="uq_dag_output_target"),
        CheckConstraint("state IN ('PENDING','PREPARED','COMMITTED')", name="ck_dag_output_state"),
    )
