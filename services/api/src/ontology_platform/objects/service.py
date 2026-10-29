from datetime import UTC, datetime
from typing import Literal

from ontology_schema.models import OntologyDefinition
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.contracts import (
    CreateObject,
    LinkInput,
    LinkView,
    ObjectPatch,
    ObjectView,
)
from ontology_platform.db.governance import GovernedService, missing
from ontology_platform.db.models import EditOverlay, Link, Object
from ontology_platform.errors import ApplicationError
from ontology_platform.metadata.storage import active_definition
from ontology_platform.objects.relationships import link_type
from ontology_platform.objects.storage import check_unique
from ontology_platform.objects.validation import object_type, validate_properties
from ontology_platform.security.interfaces import Authorizer, Principal


def resource(principal: Principal, ontology_id: str, type_id: str, object_id: str) -> str:
    return f"{principal.tenant_id}/{ontology_id}/objects/{type_id}/{object_id}"


class ObjectService(GovernedService):
    def __init__(
        self,
        sessions: sessionmaker[Session],
        authorizer: Authorizer,
        *,
        session: Session | None = None,
        record_edits: bool = True,
    ):
        super().__init__(sessions, authorizer, session=session)
        self.record_edits = record_edits

    def _user_edits(self, session: Session, row: Object, properties: list[str], actor: str) -> None:
        if not self.record_edits:
            return
        for prop in properties:
            key = (row.tenant_id, row.ontology_id, row.object_type_id, row.object_id, prop)
            overlay = session.get(EditOverlay, key)
            if overlay is None:
                overlay = EditOverlay(
                    tenant_id=row.tenant_id,
                    ontology_id=row.ontology_id,
                    object_type_id=row.object_type_id,
                    object_id=row.object_id,
                    property_id=prop,
                    source_value=None,
                )
                session.add(overlay)
            overlay.updated_by = actor
            overlay.owner, overlay.value = "user", row.properties[prop]
            overlay.schema_version, overlay.revision = row.schema_version, row.version
            overlay.execution_id = None

    def _schema(
        self, session: Session, principal: Principal, ontology_id: str, *, write: bool = False
    ) -> OntologyDefinition:
        return active_definition(
            session, self.ontology(session, principal, ontology_id, write=write)
        )

    @staticmethod
    def _get(
        session: Session, principal: Principal, ontology_id: str, type_id: str, object_id: str
    ) -> Object:
        row = session.get(Object, (principal.tenant_id, ontology_id, type_id, object_id))
        if row is None:
            raise missing("Object")
        return row

    def create(self, principal: Principal, ontology_id: str, request: CreateObject) -> ObjectView:
        return self.create_many(principal, ontology_id, [request])[0]

    def create_many(
        self, principal: Principal, ontology_id: str, requests: list[CreateObject]
    ) -> list[ObjectView]:
        if not 1 <= len(requests) <= 1000:
            raise ApplicationError("invalid_batch", "Batch requires 1–1000 objects", 422)
        with self.operation(principal, "object:create", ontology_id) as session:
            schema = self._schema(session, principal, ontology_id, write=True)
            result = []
            for request in requests:
                self.authorizer.require(
                    principal,
                    "object:create",
                    resource(principal, ontology_id, request.object_type_id, request.object_id),
                )
                typed = object_type(schema, request.object_type_id)
                properties = validate_properties(
                    typed, request.object_id, request.properties, defaults=True
                )
                check_unique(
                    session, principal.tenant_id, ontology_id, typed, request.object_id, properties
                )
                if (
                    session.get(
                        Object, (principal.tenant_id, ontology_id, typed.id, request.object_id)
                    )
                    is not None
                ):
                    raise ApplicationError("object_exists", "Object identity already exists", 409)
                row = Object(
                    tenant_id=principal.tenant_id,
                    ontology_id=ontology_id,
                    schema_version=schema.version,
                    object_type_id=typed.id,
                    object_id=request.object_id,
                    properties=properties,
                )
                session.add(row)
                session.flush()
                self._user_edits(session, row, list(properties), principal.principal_id)
                result.append(ObjectView.model_validate(row))
            return result

    def get(
        self, principal: Principal, ontology_id: str, type_id: str, object_id: str
    ) -> ObjectView:
        with self.operation(
            principal, "object:read", f"{ontology_id}/objects/{type_id}/{object_id}"
        ) as session:
            schema = self._schema(session, principal, ontology_id)
            object_type(schema, type_id)
            return ObjectView.model_validate(
                self._get(session, principal, ontology_id, type_id, object_id)
            )

    def count(self, principal: Principal, ontology_id: str, type_id: str) -> int:
        with self.operation(
            principal, "object:count", f"{ontology_id}/objects/{type_id}"
        ) as session:
            schema = self._schema(session, principal, ontology_id)
            object_type(schema, type_id)
            return (
                session.scalar(
                    select(func.count())
                    .select_from(Object)
                    .where(
                        Object.tenant_id == principal.tenant_id,
                        Object.ontology_id == ontology_id,
                        Object.object_type_id == type_id,
                    )
                )
                or 0
            )

    def patch(
        self,
        principal: Principal,
        ontology_id: str,
        type_id: str,
        object_id: str,
        request: ObjectPatch,
    ) -> ObjectView:
        with self.operation(
            principal, "object:update", f"{ontology_id}/objects/{type_id}/{object_id}"
        ) as session:
            schema = self._schema(session, principal, ontology_id, write=True)
            row = self._get(session, principal, ontology_id, type_id, object_id)
            if row.version != request.expected_version:
                raise ApplicationError("revision_conflict", "Object revision changed", 409)
            typed = object_type(schema, type_id)
            properties = validate_properties(typed, object_id, row.properties | request.properties)
            check_unique(session, principal.tenant_id, ontology_id, typed, object_id, properties)
            changed = session.scalar(
                update(Object)
                .where(
                    Object.tenant_id == principal.tenant_id,
                    Object.ontology_id == ontology_id,
                    Object.object_type_id == type_id,
                    Object.object_id == object_id,
                    Object.version == request.expected_version,
                )
                .values(
                    properties=properties,
                    version=request.expected_version + 1,
                    updated_at=datetime.now(UTC),
                )
                .returning(Object.version)
            )
            if not changed:
                raise ApplicationError("revision_conflict", "Object revision changed", 409)
            session.refresh(row)
            self._user_edits(session, row, list(request.properties), principal.principal_id)
            return ObjectView.model_validate(row)

    def delete(
        self,
        principal: Principal,
        ontology_id: str,
        type_id: str,
        object_id: str,
        expected_version: int,
    ) -> None:
        with self.operation(
            principal, "object:delete", f"{ontology_id}/objects/{type_id}/{object_id}"
        ) as session:
            self._schema(session, principal, ontology_id, write=True)
            row = self._get(session, principal, ontology_id, type_id, object_id)
            if row.version != expected_version:
                raise ApplicationError("revision_conflict", "Object revision changed", 409)
            session.execute(
                delete(Object).where(
                    Object.tenant_id == principal.tenant_id,
                    Object.ontology_id == ontology_id,
                    Object.object_type_id == type_id,
                    Object.object_id == object_id,
                    Object.version == expected_version,
                )
            )
            session.execute(
                delete(EditOverlay).where(
                    EditOverlay.tenant_id == principal.tenant_id,
                    EditOverlay.ontology_id == ontology_id,
                    EditOverlay.object_type_id == type_id,
                    EditOverlay.object_id == object_id,
                )
            )
            # FK RESTRICT deliberately requires explicit link removal first.

    def create_link(self, principal: Principal, ontology_id: str, request: LinkInput) -> LinkView:
        with self.operation(
            principal, "link:create", f"{ontology_id}/links/{request.link_type_id}"
        ) as session:
            schema = self._schema(session, principal, ontology_id, write=True)
            typed = link_type(schema, request.link_type_id)
            if (request.source_object_type_id, request.target_object_type_id) != (
                typed.source_type,
                typed.target_type,
            ):
                raise ApplicationError(
                    "invalid_link", "Endpoint types differ from link definition", 422
                )
            for type_id, object_id in [
                (request.source_object_type_id, request.source_object_id),
                (request.target_object_type_id, request.target_object_id),
            ]:
                self.authorizer.require(
                    principal, "object:link", resource(principal, ontology_id, type_id, object_id)
                )
                self._get(session, principal, ontology_id, type_id, object_id)
            source_single = typed.cardinality in {"one_to_one", "many_to_one"}
            target_single = typed.cardinality in {"one_to_one", "one_to_many"}
            if source_single:
                existing = session.scalar(
                    select(Link.source_object_id)
                    .where(
                        Link.tenant_id == principal.tenant_id,
                        Link.ontology_id == ontology_id,
                        Link.link_type_id == typed.id,
                        Link.source_object_type_id == typed.source_type,
                        Link.source_object_id == request.source_object_id,
                    )
                    .limit(1)
                )
                if existing is not None:
                    raise ApplicationError(
                        "cardinality_conflict", "Source already has its allowed link", 409
                    )
            if target_single:
                existing = session.scalar(
                    select(Link.target_object_id)
                    .where(
                        Link.tenant_id == principal.tenant_id,
                        Link.ontology_id == ontology_id,
                        Link.link_type_id == typed.id,
                        Link.target_object_type_id == typed.target_type,
                        Link.target_object_id == request.target_object_id,
                    )
                    .limit(1)
                )
                if existing is not None:
                    raise ApplicationError(
                        "cardinality_conflict", "Target already has its allowed link", 409
                    )
            row = Link(
                tenant_id=principal.tenant_id,
                ontology_id=ontology_id,
                schema_version=schema.version,
                **request.model_dump(),
            )
            session.add(row)
            session.flush()
            return LinkView.model_validate(row)

    def delete_link(self, principal: Principal, ontology_id: str, request: LinkInput) -> None:
        with self.operation(
            principal, "link:delete", f"{ontology_id}/links/{request.link_type_id}"
        ) as session:
            self._schema(session, principal, ontology_id, write=True)
            for type_id, object_id in [
                (request.source_object_type_id, request.source_object_id),
                (request.target_object_type_id, request.target_object_id),
            ]:
                self.authorizer.require(
                    principal, "object:link", resource(principal, ontology_id, type_id, object_id)
                )
            row = session.get(
                Link,
                (
                    principal.tenant_id,
                    ontology_id,
                    request.link_type_id,
                    request.source_object_type_id,
                    request.source_object_id,
                    request.target_object_type_id,
                    request.target_object_id,
                ),
            )
            if row is None:
                raise missing("Link")
            session.delete(row)

    def neighbors(
        self,
        principal: Principal,
        ontology_id: str,
        type_id: str,
        object_id: str,
        link_id: str,
        direction: Literal["forward", "inverse"] = "forward",
        limit: int = 100,
        offset: int = 0,
    ) -> list[ObjectView]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ApplicationError("invalid_page", "Invalid page bounds", 422)
        with self.operation(
            principal, "link:read", f"{ontology_id}/objects/{type_id}/{object_id}"
        ) as session:
            schema = self._schema(session, principal, ontology_id)
            self.authorizer.require(
                principal, "object:read", resource(principal, ontology_id, type_id, object_id)
            )
            self._get(session, principal, ontology_id, type_id, object_id)
            candidates = [
                t for t in schema.link_types if t.id == link_id or t.inverse_name == link_id
            ]
            if len(candidates) != 1:
                raise ApplicationError("unknown_link_type", "Unknown or ambiguous link name", 422)
            typed = candidates[0]
            inverse = direction == "inverse" or typed.inverse_name == link_id
            if type_id != (typed.target_type if inverse else typed.source_type):
                raise ApplicationError("invalid_link", "Traversal starts from the wrong type", 422)
            start_type = Link.target_object_type_id if inverse else Link.source_object_type_id
            start_id = Link.target_object_id if inverse else Link.source_object_id
            end_type = Link.source_object_type_id if inverse else Link.target_object_type_id
            end_id = Link.source_object_id if inverse else Link.target_object_id
            rows = session.scalars(
                select(Object)
                .join(
                    Link,
                    and_(
                        Object.tenant_id == Link.tenant_id,
                        Object.ontology_id == Link.ontology_id,
                        Object.object_type_id == end_type,
                        Object.object_id == end_id,
                    ),
                )
                .where(
                    Link.tenant_id == principal.tenant_id,
                    Object.tenant_id == principal.tenant_id,
                    Link.ontology_id == ontology_id,
                    Link.link_type_id == typed.id,
                    start_type == type_id,
                    start_id == object_id,
                )
                .order_by(Object.object_type_id, Object.object_id)
                .limit(limit)
                .offset(offset)
            )
            result = []
            for row in rows:
                self.authorizer.require(
                    principal,
                    "object:read",
                    resource(principal, ontology_id, row.object_type_id, row.object_id),
                )
                result.append(ObjectView.model_validate(row))
            return result
