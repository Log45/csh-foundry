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
