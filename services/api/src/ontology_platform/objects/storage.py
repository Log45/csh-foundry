"""Tenant-scoped persistence checks shared by object services and activation."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from ontology_schema.models import ObjectTypeDefinition, OntologyDefinition
from pydantic import JsonValue
from sqlalchemy import DateTime, Numeric, literal, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from ontology_platform.db.models import Object
from ontology_platform.errors import ApplicationError


def check_unique(
    session: Session,
    tenant_id: UUID,
    ontology_id: str,
    definition: ObjectTypeDefinition,
    object_id: str,
    properties: dict[str, JsonValue],
) -> None:
    for prop in definition.properties:
        value = properties.get(prop.id)
        if not prop.unique or value is None:
            continue
        expression = Object.properties[prop.id]
        predicate = expression == literal(value, type_=JSONB)
        if not prop.array and prop.data_type == "decimal":
            predicate = expression.astext.cast(Numeric) == Decimal(str(value))
        elif not prop.array and prop.data_type == "timestamp":
            predicate = expression.astext.cast(DateTime(timezone=True)) == datetime.fromisoformat(
                str(value)
            )
        found = session.scalar(
            select(Object.object_id)
            .where(
                Object.tenant_id == tenant_id,
                Object.ontology_id == ontology_id,
                Object.object_type_id == definition.id,
                Object.object_id != object_id,
                predicate,
            )
            .limit(1)
        )
        if found is not None:
            raise ApplicationError("unique_conflict", f"Property must be unique: {prop.id}", 409)


def bounded_objects(session: Session, tenant_id: UUID, ontology_id: str) -> list[Object]:
    rows = list(
        session.scalars(
            select(Object)
            .where(Object.tenant_id == tenant_id, Object.ontology_id == ontology_id)
            .order_by(Object.object_type_id, Object.object_id)
            .limit(1001)
        )
    )
    if len(rows) > 1000:
        raise ApplicationError(
            "activation_too_large", "Phase 1 activation supports at most 1000 objects", 409
        )
    return rows


def validate_live_objects(
    session: Session, tenant_id: UUID, ontology_id: str, definition: OntologyDefinition
) -> list[Object]:
    from ontology_platform.objects.validation import object_type, validate_properties

    rows = bounded_objects(session, tenant_id, ontology_id)
    for row in rows:
        typed = object_type(definition, row.object_type_id)
        validate_properties(typed, row.object_id, row.properties)
    for row in rows:
        typed = object_type(definition, row.object_type_id)
        check_unique(session, tenant_id, ontology_id, typed, row.object_id, row.properties)
    return rows
