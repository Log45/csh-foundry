"""Foundational property reconciliation; callers supply one validated source update.

No file connectors, batch ingestion, or implicit deletion are implemented here.
"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, JsonValue
from sqlalchemy import literal, select
from sqlalchemy.dialects.postgresql import JSONB

from ontology_platform.contracts import APIModel, CreateObject, ObjectPatch, ObjectView
from ontology_platform.db.governance import GovernedService, missing
from ontology_platform.db.models import EditOverlay, ReconciliationConflict, Version
from ontology_platform.errors import ApplicationError
from ontology_platform.metadata.storage import active_definition
from ontology_platform.objects.service import ObjectService, resource
from ontology_platform.objects.validation import object_type, validate_properties
from ontology_platform.security.interfaces import Principal


class SourceUpdate(APIModel):
    source: str = Field(max_length=200)
    owner: Literal["source", "pipeline"] = "source"
    expected_version: int = Field(strict=True, ge=1)
    properties: dict[str, JsonValue] = Field(max_length=64)
    policy: Literal["edit_wins", "source_wins", "reject", "manual"] = "edit_wins"


class ReconciliationResult(APIModel):
    object: ObjectView
    conflicts: list[UUID]
    decision: Literal["accepted", "preserved", "conflict", "resolution_required"]


class ReconciliationService(GovernedService):
    def refresh(
        self,
        principal: Principal,
        ontology_id: str,
        type_id: str,
        object_id: str,
        request: SourceUpdate,
    ) -> ReconciliationResult:
        with self.operation(
            principal, "edit:reconcile", f"{ontology_id}/objects/{type_id}/{object_id}"
        ) as session:
            schema = active_definition(
                session, self.ontology(session, principal, ontology_id, write=True)
            )
            objects = ObjectService(
                self.sessions, self.authorizer, session=session, record_edits=False
            )
            current = objects.get(principal, ontology_id, type_id, object_id)
            if current.version != request.expected_version:
                raise ApplicationError("revision_conflict", "Object revision changed", 409)
            validate_properties(
                object_type(schema, type_id), object_id, current.properties | request.properties
            )
            accepted: dict[str, JsonValue] = {}
            conflicts: list[UUID] = []
            overlays: dict[str, EditOverlay] = {}
            planned: list[tuple[str, EditOverlay | None, bool, JsonValue, bool]] = []
            for prop, incoming in request.properties.items():
                self.authorizer.require(
                    principal,
                    "property:update",
                    resource(principal, ontology_id, type_id, object_id) + f"/properties/{prop}",
                )
                overlay = session.get(
                    EditOverlay, (principal.tenant_id, ontology_id, type_id, object_id, prop)
                )
                if overlay is not None and overlay.schema_version != schema.version:
                    previous = session.get(
                        Version, (principal.tenant_id, ontology_id, overlay.schema_version)
                    )
                    assert previous is not None
                    from ontology_schema.models import OntologyDefinition

                    old_type = object_type(
                        OntologyDefinition.model_validate_json(previous.definition_json), type_id
                    )
                    old_property = next(p for p in old_type.properties if p.id == prop)
                    new_property = next(
                        p for p in object_type(schema, type_id).properties if p.id == prop
                    )
                    if (old_property.data_type, old_property.array) != (
                        new_property.data_type,
                        new_property.array,
                    ):
                        raise ApplicationError(
                            "overlay_schema_conflict",
                            "Overlay type changed; a governed edit must rebase it",
                            409,
                        )
                    try:
                        new_property.validate_value(overlay.value)
                    except ValueError as exc:
                        raise ApplicationError(
                            "overlay_schema_conflict",
                            "Overlay is incompatible with the active schema",
                            409,
                        ) from exc
                if overlay is not None and overlay.source not in {None, request.source}:
                    raise ApplicationError(
                        "source_ownership_conflict", "Property belongs to another source", 409
                    )
                governed = (overlay is None and prop in current.properties) or (
                    overlay is not None and overlay.owner in {"user", "action"}
                )
                if governed and request.policy == "source_wins":
                    self.authorizer.require(
                        principal,
                        "edit:override",
                        resource(principal, ontology_id, type_id, object_id)
                        + f"/properties/{prop}",
                    )
                preserve = governed and request.policy != "source_wins"
                different = prop not in current.properties or current.properties[prop] != incoming
                if preserve and different and request.policy in {"reject", "manual"}:
                    conflict = session.scalar(
                        select(ReconciliationConflict)
                        .where(
                            ReconciliationConflict.tenant_id == principal.tenant_id,
                            ReconciliationConflict.ontology_id == ontology_id,
                            ReconciliationConflict.object_type_id == type_id,
                            ReconciliationConflict.object_id == object_id,
                            ReconciliationConflict.property_id == prop,
                            ReconciliationConflict.source == request.source,
                            ReconciliationConflict.observed_revision == current.version,
                            ReconciliationConflict.schema_version == schema.version,
                            ReconciliationConflict.status == "OPEN",
                            ReconciliationConflict.incoming == literal(incoming, type_=JSONB()),
                        )
                        .limit(1)
                    )
                    if conflict is None:
                        conflict = ReconciliationConflict(
                            tenant_id=principal.tenant_id,
                            ontology_id=ontology_id,
                            id=uuid4(),
                            object_type_id=type_id,
                            object_id=object_id,
                            property_id=prop,
                            incoming=incoming,
                            source=request.source,
                            observed_revision=current.version,
                            schema_version=schema.version,
                        )
                        session.add(conflict)
                    conflicts.append(conflict.id)
                if different and not preserve:
                    accepted[prop] = incoming
                planned.append((prop, overlay, governed, incoming, preserve))
            if conflicts:
                session.flush()
                return ReconciliationResult(
                    object=current,
                    conflicts=conflicts,
                    decision="conflict" if request.policy == "reject" else "resolution_required",
                )
            for prop, overlay, _governed, incoming, preserve in planned:
                if overlay is None:
                    overlay = EditOverlay(
                        tenant_id=principal.tenant_id,
                        ontology_id=ontology_id,
                        object_type_id=type_id,
                        object_id=object_id,
                        property_id=prop,
                        source_value=None,
                        owner="user",
                    )
                    session.add(overlay)
                if not preserve:
                    overlay.owner, overlay.source = request.owner, request.source
                    overlay.execution_id = None
                overlay.updated_by = principal.principal_id
                overlay.value = current.properties.get(prop) if preserve else incoming
                overlay.source_value = incoming
                overlay.schema_version, overlay.revision = schema.version, current.version
                overlays[prop] = overlay
            if accepted:
                current = objects.patch(
                    principal,
                    ontology_id,
                    type_id,
                    object_id,
                    ObjectPatch(expected_version=current.version, properties=accepted),
                )
            for overlay in overlays.values():
                overlay.revision = current.version
            session.flush()
            return ReconciliationResult(
                object=current, conflicts=[], decision="accepted" if accepted else "preserved"
            )

    def resolve(
        self,
        principal: Principal,
        ontology_id: str,
        conflict_id: UUID,
        *,
        expected_version: int,
        accept_source: bool,
    ) -> ReconciliationResult:
        with self.operation(
            principal, "edit:resolve", f"{ontology_id}/conflicts/{conflict_id}"
        ) as session:
            schema = active_definition(
                session, self.ontology(session, principal, ontology_id, write=True)
            )
            conflict = session.get(
                ReconciliationConflict, (principal.tenant_id, ontology_id, conflict_id)
            )
            if conflict is None:
                raise missing("Reconciliation conflict")
            if conflict.status != "OPEN" or conflict.schema_version != schema.version:
                raise ApplicationError(
                    "reconciliation_conflict",
                    "Conflict is resolved or schema changed; refresh again",
                    409,
                )
            service = ReconciliationService(self.sessions, self.authorizer, session=session)
            if accept_source:
                result = service.refresh(
                    principal,
                    ontology_id,
                    conflict.object_type_id,
                    conflict.object_id,
                    SourceUpdate(
                        source=conflict.source,
                        expected_version=expected_version,
                        properties={conflict.property_id: conflict.incoming},
                        policy="source_wins",
                    ),
                )
            else:
                obj = ObjectService(self.sessions, self.authorizer, session=session).get(
                    principal, ontology_id, conflict.object_type_id, conflict.object_id
                )
                if obj.version != expected_version:
                    raise ApplicationError("revision_conflict", "Object revision changed", 409)
                result = ReconciliationResult(object=obj, conflicts=[], decision="preserved")
            conflict.status = "ACCEPTED" if accept_source else "PRESERVED"
            conflict.resolved_by, conflict.resolved_at = principal.principal_id, datetime.now(UTC)
            return result

    def create_from_source(
        self,
        principal: Principal,
        ontology_id: str,
        request: "CreateObject",
        source: str,
        *,
        owner: Literal["source", "pipeline"] = "source",
    ) -> ObjectView:
        """Create with source ownership; existing identities cannot be adopted."""
        with self.operation(
            principal,
            "edit:initialize_source",
            f"{ontology_id}/objects/{request.object_type_id}/{request.object_id}",
        ) as session:
            objects = ObjectService(
                self.sessions, self.authorizer, session=session, record_edits=False
            )
            created = objects.create(principal, ontology_id, request)
            for prop, value in created.properties.items():
                self.authorizer.require(
                    principal,
                    "property:update",
                    resource(principal, ontology_id, request.object_type_id, request.object_id)
                    + f"/properties/{prop}",
                )
                session.add(
                    EditOverlay(
                        tenant_id=principal.tenant_id,
                        ontology_id=ontology_id,
                        object_type_id=request.object_type_id,
                        object_id=request.object_id,
                        property_id=prop,
                        owner=owner,
                        source=source,
                        value=value,
                        source_value=value,
                        revision=created.version,
                        schema_version=created.schema_version,
                        updated_by=principal.principal_id,
                        execution_id=None,
                    )
                )
            session.flush()
            return created
