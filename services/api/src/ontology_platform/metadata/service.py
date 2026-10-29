from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from ontology_schema.models import OntologyDefinition
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ontology_platform.contracts import (
    Compatibility,
    MigrationUpdate,
    OntologyView,
    PlanInput,
    PlanView,
    VersionView,
)
from ontology_platform.db.governance import GovernedService, missing
from ontology_platform.db.models import (
    Activation,
    LinkType,
    MigrationPlan,
    ObjectType,
    Ontology,
    Version,
)
from ontology_platform.errors import ApplicationError
from ontology_platform.metadata.compatibility import compare
from ontology_platform.metadata.storage import (
    active_definition,
    definition_of,
    digest,
    version_row,
    version_view,
)
from ontology_platform.security.interfaces import Principal
from ontology_platform.security.query import ObjectAuthorizer


class RegistryService(GovernedService):
    @staticmethod
    def _identity(principal: Principal, ontology: Ontology, definition: OntologyDefinition) -> None:
        if definition.tenant_id != principal.tenant_id:
            raise ApplicationError("forbidden", "Definition belongs to another tenant", 403)
        if definition.id != ontology.id or definition.namespace != ontology.namespace:
            raise ApplicationError(
                "identity_immutable", "Ontology ID and namespace cannot change", 409
            )

    @staticmethod
    def _write_draft(
        session: Session,
        ontology: Ontology,
        definition: OntologyDefinition,
        *,
        replace: bool = False,
    ) -> Version:
        key = (ontology.tenant_id, ontology.id, definition.version)
        row = session.get(Version, key)
        if row is not None and (not replace or row.status != "DRAFT"):
            raise ApplicationError(
                "version_immutable", "Version exists; only drafts may be replaced", 409
            )
        if row is None:
            row = Version(
                tenant_id=ontology.tenant_id,
                ontology_id=ontology.id,
                version=definition.version,
                status="DRAFT",
            )
            session.add(row)
        else:
            session.execute(
                delete(LinkType).where(
                    LinkType.tenant_id == ontology.tenant_id,
                    LinkType.ontology_id == ontology.id,
                    LinkType.schema_version == definition.version,
                )
            )
            session.execute(
                delete(ObjectType).where(
                    ObjectType.tenant_id == ontology.tenant_id,
                    ObjectType.ontology_id == ontology.id,
                    ObjectType.schema_version == definition.version,
                )
            )
        row.definition_json = definition.canonical_json()
        row.content_hash = digest(definition)
        session.flush()
        for typed in definition.object_types:
            session.add(
                ObjectType(
                    tenant_id=ontology.tenant_id,
                    ontology_id=ontology.id,
                    schema_version=definition.version,
                    id=typed.id,
                    definition=typed.model_dump(mode="json"),
                )
            )
        session.flush()
        for link in definition.link_types:
            session.add(
                LinkType(
                    tenant_id=ontology.tenant_id,
                    ontology_id=ontology.id,
                    schema_version=definition.version,
                    id=link.id,
                    source_type=link.source_type,
                    target_type=link.target_type,
                    cardinality=link.cardinality,
                    definition=link.model_dump(mode="json"),
                )
            )
        session.flush()
        return row

    def create(self, principal: Principal, definition: OntologyDefinition) -> VersionView:
        with self.operation(principal, "ontology:create", definition.id) as session:
            if definition.tenant_id != principal.tenant_id:
                raise ApplicationError("forbidden", "Definition belongs to another tenant", 403)
            if session.get(Ontology, (principal.tenant_id, definition.id)) is not None:
                raise ApplicationError("ontology_exists", "Ontology already exists", 409)
            ontology = Ontology(
                tenant_id=principal.tenant_id, id=definition.id, namespace=definition.namespace
            )
            session.add(ontology)
            session.flush()
            return version_view(self._write_draft(session, ontology, definition))

    def list_ontologies(
        self, principal: Principal, limit: int = 100, offset: int = 0
    ) -> list[OntologyView]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ApplicationError("invalid_page", "Invalid page bounds", 422)
        with self.operation(principal, "ontology:read", "ontologies") as session:
            rows = list(
                session.scalars(
                    select(Ontology)
                    .where(Ontology.tenant_id == principal.tenant_id)
                    .order_by(Ontology.id)
                    .limit(limit)
                    .offset(offset)
                )
            )
            for row in rows:
                self.authorizer.require(
                    principal, "ontology:read", f"{principal.tenant_id}/{row.id}"
                )
            return [OntologyView.model_validate(row) for row in rows]

    def get(self, principal: Principal, ontology_id: str) -> OntologyView:
        with self.operation(principal, "ontology:read", ontology_id) as session:
            return OntologyView.model_validate(self.ontology(session, principal, ontology_id))

    def draft(
        self,
        principal: Principal,
        ontology_id: str,
        definition: OntologyDefinition,
        *,
        replace: bool = False,
        expected_hash: str | None = None,
    ) -> VersionView:
        with self.operation(principal, "schema:write", ontology_id) as session:
            ontology = self.ontology(session, principal, ontology_id, write=True)
            self._identity(principal, ontology, definition)
            if expected_hash is not None:
                current = session.get(
                    Version, (principal.tenant_id, ontology_id, definition.version)
                )
                if current is None or current.content_hash != expected_hash:
                    raise ApplicationError(
                        "draft_changed", "Draft changed; reload before saving", 412
                    )
            return version_view(self._write_draft(session, ontology, definition, replace=replace))

    def versions(
        self, principal: Principal, ontology_id: str, limit: int = 100, offset: int = 0
    ) -> list[VersionView]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ApplicationError("invalid_page", "Invalid page bounds", 422)
        with self.operation(principal, "schema:read", ontology_id) as session:
            self.ontology(session, principal, ontology_id)
            return [
                version_view(v)
                for v in session.scalars(
                    select(Version)
                    .where(
                        Version.tenant_id == principal.tenant_id, Version.ontology_id == ontology_id
                    )
                    .order_by(Version.version)
                    .limit(limit)
                    .offset(offset)
                )
            ]

    def version(self, principal: Principal, ontology_id: str, version: str) -> VersionView:
        with self.operation(principal, "schema:read", ontology_id) as session:
            ontology = self.ontology(session, principal, ontology_id)
            return version_view(version_row(session, ontology, version))

    def validate(self, principal: Principal, ontology_id: str, version: str) -> Compatibility:
        with self.operation(principal, "schema:validate", ontology_id) as session:
            ontology = self.ontology(session, principal, ontology_id)
            proposed = definition_of(version_row(session, ontology, version))
            previous = active_definition(session, ontology) if ontology.active_version else None
            return compare(previous, proposed)

    def create_plan(
        self, principal: Principal, ontology_id: str, version: str, request: PlanInput
    ) -> PlanView:
        with self.operation(principal, "migration:plan", ontology_id) as session:
            ontology = self.ontology(session, principal, ontology_id, write=True)
            target = version_row(session, ontology, version)
            keys = [(u.object_type_id, u.object_id) for u in request.updates]
            if len(keys) != len(set(keys)):
                raise ApplicationError("invalid_plan", "Duplicate migration object identities", 422)
            plan = MigrationPlan(
                tenant_id=principal.tenant_id,
                ontology_id=ontology_id,
                id=uuid4(),
                target_version=version,
                base_version=ontology.active_version,
                content_hash=target.content_hash,
                updates=[u.model_dump(mode="json") for u in request.updates],
                created_by=principal.principal_id,
            )
            session.add(plan)
            session.flush()
            return PlanView.model_validate(plan)

    def approve_plan(self, principal: Principal, ontology_id: str, plan_id: UUID) -> PlanView:
        with self.operation(principal, "migration:approve", ontology_id) as session:
            ontology = self.ontology(session, principal, ontology_id, write=True)
            plan = session.get(MigrationPlan, (principal.tenant_id, ontology_id, plan_id))
            if plan is None:
                raise missing("Migration plan")
            target = version_row(session, ontology, plan.target_version)
            if (
                plan.base_version != ontology.active_version
                or plan.content_hash != target.content_hash
            ):
                raise ApplicationError(
                    "stale_plan", "Plan base or target changed; create a new plan", 409
                )
            if plan.approved_at is None:
                plan.approved_at, plan.approved_by = datetime.now(UTC), principal.principal_id
                session.flush()
            return PlanView.model_validate(plan)

    @staticmethod
    def _approved_plan(
        session: Session, ontology: Ontology, target: Version, plan_id: UUID | None, required: bool
    ) -> MigrationPlan | None:
        if plan_id is None:
            if required:
                raise ApplicationError(
                    "migration_required", "Breaking changes require an approved plan", 409
                )
            return None
        plan = session.get(MigrationPlan, (ontology.tenant_id, ontology.id, plan_id))
        if (
            plan is None
            or plan.approved_at is None
            or plan.approved_by is None
            or plan.base_version != ontology.active_version
            or plan.target_version != target.version
            or plan.content_hash != target.content_hash
        ):
            raise ApplicationError(
                "invalid_plan", "An approved plan matching base and target is required", 409
            )
        return plan

    def publish(
        self, principal: Principal, ontology_id: str, version: str, plan_id: UUID | None = None
    ) -> VersionView:
        with self.operation(principal, "schema:publish", ontology_id) as session:
            ontology = self.ontology(session, principal, ontology_id, write=True)
            target = version_row(session, ontology, version)
            if target.status != "DRAFT":
                raise ApplicationError("version_immutable", "Version is already published", 409)
            previous = active_definition(session, ontology) if ontology.active_version else None
            comparison = compare(previous, definition_of(target))
            self._approved_plan(
                session, ontology, target, plan_id, comparison.classification == "breaking"
            )
            target.status, target.published_at = "PUBLISHED", datetime.now(UTC)
            target.published_by = principal.principal_id
            session.flush()
            return version_view(target)

    def activate(
        self, principal: Principal, ontology_id: str, version: str, plan_id: UUID | None = None
    ) -> OntologyView:
        # Activation is bounded. Larger migrations require a later durable worker path.
        from ontology_platform.db.models import Object
        from ontology_platform.objects.relationships import validate_live_links
        from ontology_platform.objects.storage import validate_live_objects
        from ontology_platform.objects.validation import object_type, validate_properties

        with self.operation(principal, "schema:activate", ontology_id) as session:
            ontology = self.ontology(session, principal, ontology_id, write=True)
            target = version_row(session, ontology, version)
            if target.status != "PUBLISHED":
                raise ApplicationError("schema_unpublished", "Publish before activating", 409)
            if ontology.active_version == version:
                raise ApplicationError("already_active", "Version is already active", 409)
            proposed = definition_of(target)
            previous = active_definition(session, ontology) if ontology.active_version else None
            comparison = compare(previous, proposed)
            plan = self._approved_plan(
                session, ontology, target, plan_id, comparison.classification == "breaking"
            )
            self.authorizer.require(
                principal, "object:read", f"{principal.tenant_id}/{ontology_id}/objects"
            )
            self.authorizer.require(
                principal, "link:read", f"{principal.tenant_id}/{ontology_id}/links"
            )
            if plan is not None:
                for item in plan.updates:
                    update = MigrationUpdate.model_validate(item)
                    self.authorizer.require(
                        principal,
                        "object:update",
                        f"{principal.tenant_id}/{ontology_id}/objects/{update.object_type_id}/{update.object_id}",
                    )
                    row = session.get(
                        Object,
                        (principal.tenant_id, ontology_id, update.object_type_id, update.object_id),
                    )
                    if row is None:
                        raise missing("Migration object")
                    if row.version != update.expected_version:
                        raise ApplicationError(
                            "revision_conflict", "Migration object revision changed", 409
                        )
                    if isinstance(self.authorizer, ObjectAuthorizer):
                        self.authorizer.object_check(
                            principal,
                            "object:update",
                            ontology_id,
                            update.object_type_id,
                            update.object_id,
                            properties=update.properties,
                            changed=tuple(update.properties),
                        )
                    row.properties = validate_properties(
                        object_type(proposed, row.object_type_id), row.object_id, update.properties
                    )
                session.flush()
            if isinstance(self.authorizer, ObjectAuthorizer):
                from ontology_platform.objects.storage import bounded_objects

                for current in bounded_objects(session, principal.tenant_id, ontology_id):
                    self.authorizer.object_check(
                        principal,
                        "object:update",
                        ontology_id,
                        current.object_type_id,
                        current.object_id,
                        changed=tuple(current.properties),
                    )
            rows = validate_live_objects(session, principal.tenant_id, ontology_id, proposed)
            links = validate_live_links(session, principal.tenant_id, ontology_id, proposed)
            for row in rows:
                self.authorizer.require(
                    principal,
                    "object:update",
                    f"{principal.tenant_id}/{ontology_id}/objects/{row.object_type_id}/{row.object_id}",
                )
                if isinstance(self.authorizer, ObjectAuthorizer):
                    self.authorizer.object_check(
                        principal, "object:update", ontology_id, row.object_type_id, row.object_id
                    )
                row.schema_version = version
                row.version += 1
                row.updated_at = datetime.now(UTC)
            for link in links:
                self.authorizer.require(
                    principal,
                    "link:update",
                    f"{principal.tenant_id}/{ontology_id}/links/{link.link_type_id}",
                )
                link.schema_version = version
            session.add(
                Activation(
                    tenant_id=principal.tenant_id,
                    ontology_id=ontology_id,
                    id=uuid4(),
                    target_version=version,
                    previous_version=ontology.active_version,
                    plan_id=plan.id if plan else None,
                    actor=principal.principal_id,
                )
            )
            ontology.active_version = version
            session.flush()
            return OntologyView.model_validate(ontology)

    def object_types(self, principal: Principal, ontology_id: str) -> list[dict[str, object]]:
        with self.operation(principal, "schema:read", ontology_id) as session:
            ontology = self.ontology(session, principal, ontology_id)
            return [
                typed.model_dump(mode="json")
                for typed in active_definition(session, ontology).object_types
            ]
