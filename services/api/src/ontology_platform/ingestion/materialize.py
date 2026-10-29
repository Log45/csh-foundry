"""Compose existing governed services; connectors never write operational storage."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ontology_platform.contracts import CreateObject, LinkInput
from ontology_platform.db.models import (
    IngestionMapping,
    IngestionStage,
    Link,
    SourceLink,
    SourceObject,
)
from ontology_platform.edits.service import ReconciliationService, SourceUpdate
from ontology_platform.errors import ApplicationError
from ontology_platform.ingestion.contracts import SourceInput
from ontology_platform.ingestion.service import IngestionService, origin
from ontology_platform.metadata.storage import active_definition
from ontology_platform.objects.relationships import link_type
from ontology_platform.objects.service import ObjectService
from ontology_platform.security.interfaces import Principal


class Materializer:
    def __init__(
        self, service: IngestionService, session: Session, principal: Principal, ontology: str
    ):
        self.service, self.session, self.p, self.ontology = service, session, principal, ontology
        self.objects = ObjectService(
            service.sessions, service.authorizer, session=session, record_edits=False
        )
        self.reconcile = ReconciliationService(
            service.sessions, service.authorizer, session=session
        )

    def source(self, row: IngestionStage) -> SourceInput:
        mapping = self.session.get(
            IngestionMapping, (self.p.tenant_id, self.ontology, row.mapping_id, row.mapping_version)
        )
        assert mapping is not None
        return self.service.configuration(self.session, self.p, self.ontology, mapping)[1]

    def objects_for(self, row: IngestionStage) -> tuple[bool, bool, bool]:
        source = self.source(row)
        assert row.object_id is not None and row.source_key is not None
        key = (self.p.tenant_id, self.ontology, row.object_type, row.object_id)
        owner = self.session.get(SourceObject, key)
        old_identity = self.session.scalar(
            select(SourceObject).where(
                SourceObject.tenant_id == self.p.tenant_id,
                SourceObject.ontology_id == self.ontology,
                SourceObject.source_id == source.id,
                SourceObject.namespace == source.identity_namespace,
                SourceObject.source_key == row.source_key,
                SourceObject.object_type == row.object_type,
            )
        )
        if old_identity is not None and old_identity.object_id != row.object_id:
            raise ApplicationError(
                "source_identity_changed", "Source identity cannot rewrite an object ID", 409
            )
        if owner is not None and (owner.source_id, owner.namespace, owner.source_key) != (
            source.id,
            source.identity_namespace,
            row.source_key,
        ):
            raise ApplicationError(
                "source_identity_collision",
                "Object is associated with another source identity",
                409,
            )
        try:
            current = self.objects.get(self.p, self.ontology, row.object_type, row.object_id)
        except ApplicationError as exc:
            if exc.code != "not_found":
                raise
            current = None
        created = current is None
        updated = False
        if current is None:
            if owner is not None:
                if source.reconciliation != "source_wins":
                    raise ApplicationError(
                        "governed_deletion_conflict", "Previously sourced object was deleted", 409
                    )
                self.service.authorizer.require(
                    self.p,
                    "edit:override",
                    f"{self.p.tenant_id}/{self.ontology}/objects/{row.object_type}/{row.object_id}",
                )
            self.reconcile.create_from_source(
                self.p,
                self.ontology,
                CreateObject(
                    object_type_id=row.object_type,
                    object_id=row.object_id,
                    properties=row.properties,
                ),
                origin(source),
                owner=source.owner,
            )
        else:
            result = self.reconcile.refresh(
                self.p,
                self.ontology,
                row.object_type,
                row.object_id,
                SourceUpdate(
                    source=origin(source),
                    owner=source.owner,
                    expected_version=current.version,
                    properties=row.properties,
                    policy=source.reconciliation,
                ),
            )
            if result.conflicts:
                return False, False, True
            updated = result.object.version != current.version
        if owner is None:
            self.session.add(
                SourceObject(
                    tenant_id=self.p.tenant_id,
                    ontology_id=self.ontology,
                    object_type=row.object_type,
                    object_id=row.object_id,
                    source_id=source.id,
                    source_version=source.version,
                    namespace=source.identity_namespace,
                    source_key=row.source_key,
                )
            )
        else:
            owner.source_version = source.version
        self.session.flush()
        return created, updated, False

    def links_for(self, row: IngestionStage) -> tuple[int, bool]:
        source = self.source(row)
        schema = active_definition(
            self.session, self.service.ontology(self.session, self.p, self.ontology, write=True)
        )
        created = 0
        conflict = False
        for value in row.relationships:
            assert isinstance(value, dict)
            link_id, target = value["link"], value["target"]
            assert (
                isinstance(link_id, str) and isinstance(target, str) and row.object_id is not None
            )
            typed = link_type(schema, link_id)
            self.service.authorizer.require(
                self.p, "link:read", f"{self.p.tenant_id}/{self.ontology}/links/{typed.id}"
            )
            self.objects.get(self.p, self.ontology, row.object_type, row.object_id)
            self.objects.get(self.p, self.ontology, typed.target_type, target)
            key = (self.p.tenant_id, self.ontology, row.object_type, row.object_id, typed.id)
            state = self.session.get(SourceLink, key)
            edgekey = (
                self.p.tenant_id,
                self.ontology,
                typed.id,
                row.object_type,
                row.object_id,
                typed.target_type,
                target,
            )
            desired = self.session.get(Link, edgekey)
            request = LinkInput(
                link_type_id=typed.id,
                source_object_type_id=row.object_type,
                source_object_id=row.object_id,
                target_object_type_id=typed.target_type,
                target_object_id=target,
            )
            if state is not None:
                old = self.session.get(
                    Link,
                    (
                        self.p.tenant_id,
                        self.ontology,
                        typed.id,
                        row.object_type,
                        row.object_id,
                        state.target_type,
                        state.target_id,
                    ),
                )
                governed = (
                    not state.managed or old is None or old.created_at != state.edge_created_at
                )
                if state.target_id == target and desired is not None:
                    if governed:
                        state.managed = False
                    continue
                if governed and source.reconciliation != "source_wins":
                    conflict = True
                    continue
                if governed:
                    self.service.authorizer.require(
                        self.p,
                        "edit:override",
                        f"{self.p.tenant_id}/{self.ontology}/links/{typed.id}",
                    )
                if old is not None:
                    self.objects.delete_link(
                        self.p,
                        self.ontology,
                        request.model_copy(
                            update={
                                "target_object_type_id": state.target_type,
                                "target_object_id": state.target_id,
                            }
                        ),
                    )
            if desired is None:
                desired_view = self.objects.create_link(self.p, self.ontology, request)
                created += 1
                timestamp = desired_view.created_at
                managed = True
            else:
                timestamp = desired.created_at
                managed = False
            if state is None:
                self.session.add(
                    SourceLink(
                        tenant_id=self.p.tenant_id,
                        ontology_id=self.ontology,
                        object_type=row.object_type,
                        object_id=row.object_id,
                        link_type=typed.id,
                        target_type=typed.target_type,
                        target_id=target,
                        managed=managed,
                        edge_created_at=timestamp,
                    )
                )
            else:
                state.target_type, state.target_id = typed.target_type, target
                state.managed, state.edge_created_at = managed, timestamp
            self.session.flush()
        return created, conflict
