"""Application governance composes the registry and canonical operational services."""

import time
from typing import Any
from uuid import UUID, uuid4

from ontology_schema.models import OntologyDefinition
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.actions.contracts import ActionRequest, ActionResult, ExecuteRequest
from ontology_platform.actions.deadline import action_deadline
from ontology_platform.actions.service import ActionExecutionService
from ontology_platform.applications.contracts import (
    Diagnostic,
    Document,
    Draft,
    Publish,
    Published,
    RuntimeQuery,
    Save,
    Validation,
    Value,
    validate,
)
from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.branching.service import page
from ontology_platform.db.governance import missing
from ontology_platform.db.models import ApplicationDraft, ApplicationVersion, Resource, Version
from ontology_platform.errors import ApplicationError
from ontology_platform.metadata.storage import definition_of
from ontology_platform.projects.contracts import ResourceView
from ontology_platform.projects.service import ProjectService, conflict
from ontology_platform.queries.ast import (
    AggregateRequest,
    AggregateResult,
    Negation,
    Predicate,
    QueryPage,
    QueryRequest,
)
from ontology_platform.queries.cursor import CursorCodec
from ontology_platform.queries.service import QueryService
from ontology_platform.security.interfaces import Authorizer, Principal


class ApplicationService(ProjectService):
    def __init__(
        self,
        sessions: sessionmaker[Session],
        authorizer: Authorizer,
        cursors: CursorCodec | None = None,
    ):
        super().__init__(sessions, authorizer)
        self.cursors = cursors or CursorCodec()

    def application(self, s: Session, p: Principal, key: UUID, write: bool = False) -> Resource:
        row = self.resource(s, p, key)
        if row.resource_type != "APPLICATION":
            raise missing("Application")
        if write:
            self.project(s, p, row.project_id, write=True)
        return row

    def create(self, p: Principal, project: UUID, body: CreateArtifact) -> ResourceView:
        with self.scope(p) as s:
            self.project(s, p, project, write=True)
            self.destination(s, p, project, body.folder_id)
            row = Resource(
                tenant_id=p.tenant_id,
                id=uuid4(),
                project_id=project,
                resource_type="APPLICATION",
                **body.model_dump(),
                created_by=p.principal_id,
                updated_by=p.principal_id,
            )
            s.add(row)
            s.flush()
            self.audit(s, p, "application_create", row.id)
            return ResourceView.model_validate(row)

    def references(
        self, s: Session, p: Principal, doc: Document, *, active: bool = True
    ) -> dict[str, OntologyDefinition]:
        schemas = {}
        for dep in sorted(doc.dependencies, key=lambda d: (d.ontology_id, d.id)):
            row = self.resource(s, p, dep.resource_id)
            if (
                row.resource_type
                not in {"ONTOLOGY_VERSION", "ONTOLOGY_ACTION", "ONTOLOGY_OBJECT_TYPE"}
                or row.ontology_id != dep.ontology_id
                or row.schema_version != dep.schema_version
            ):
                raise missing("Dependency")
            self.authorizer.require(p, "schema:read", f"{p.tenant_id}/{dep.ontology_id}")
            ontology = self.ontology(s, p, dep.ontology_id)
            version = s.get(Version, (p.tenant_id, dep.ontology_id, dep.schema_version))
            if version is None or version.status != "PUBLISHED":
                raise missing("Dependency")
            if active and ontology.active_version != dep.schema_version:
                raise conflict("Dependency requires explicit schema rebinding")
            schemas[dep.id] = definition_of(version)
        return schemas

    def validate_in(self, s: Session, p: Principal, doc: Document) -> Validation:
        result = validate(doc)
        try:
            schemas = self.references(s, p, doc)
            result_types = {}
            for source in doc.sources:
                if source.dependency not in schemas:
                    continue
                schema = schemas[source.dependency]
                # Reuse canonical compiler for structural contracts. Runtime applies viewer policy.
                types = {t.id: t for t in schema.object_types}
                if source.query.object_type not in types:
                    raise ValueError("Object type unavailable")
                current = types[source.query.object_type]
                for step in source.query.traverse:
                    link = next((link for link in schema.link_types if link.id == step.link), None)
                    if link is None:
                        raise ValueError("Link unavailable")
                    expected = link.source_type if step.direction == "forward" else link.target_type
                    if current.id != expected:
                        raise ValueError("Link source mismatch")
                    current = types[
                        link.target_type if step.direction == "forward" else link.source_type
                    ]
                properties = {v.id for v in current.properties}
                result_types[source.id] = current
                # Validate filters against metadata without operational reads or viewer grants.
                for request in (source.query, source.aggregate):
                    if request is None:
                        continue
                    if request.traverse != source.query.traverse:
                        raise ValueError("Aggregate traversal mismatch")
                    initial = types[request.object_type]
                    checks = [(request.filter, initial), (request.result_filter, current)]
                    for step in request.traverse:
                        link = next(v for v in schema.link_types if v.id == step.link)
                        target = types[
                            link.target_type if step.direction == "forward" else link.source_type
                        ]
                        checks.append((step.filter, target))
                    for condition, typed in checks:
                        pending = [condition] if condition else []
                        while pending:
                            predicate = pending.pop()
                            if isinstance(predicate, Predicate):
                                prop = next(
                                    (v for v in typed.properties if v.id == predicate.property),
                                    None,
                                )
                                if prop is None:
                                    raise ValueError("Filter property unavailable")
                                if predicate.operator not in {"is_null", "is_not_null"}:
                                    prop.validate_value(predicate.value)
                            elif isinstance(predicate, Negation):
                                pending.append(predicate.condition)
                            else:
                                pending.extend(predicate.conditions)
                if (
                    set(source.query.select or ()) | {v.property for v in source.query.order_by}
                ) - properties:
                    raise ValueError("Property unavailable")
                # Dynamic source filters apply before traversal.
                if set(source.filters) - {v.id for v in types[source.query.object_type].properties}:
                    raise ValueError("Filter property unavailable")
                if source.aggregate:
                    if source.aggregate.object_type != source.query.object_type:
                        raise ValueError("Aggregate type mismatch")
                    used = {m.property for m in source.aggregate.metrics if m.property}
                    if source.aggregate.group_by:
                        used.add(source.aggregate.group_by)
                    if used - properties:
                        raise ValueError("Aggregate property unavailable")
            selection_types = {}
            for app_page in doc.pages:
                for widget in app_page.widgets:
                    if widget.source in result_types:
                        typed = result_types[widget.source]
                        if set(widget.columns) - {v.id for v in typed.properties}:
                            raise ValueError("Widget property unavailable")
                        if widget.kind in {"table", "list"} and widget.state:
                            selection_types[widget.state] = typed
            states = {state.id: state for state in doc.states}
            for binding in doc.actions:
                if binding.dependency not in schemas:
                    continue
                schema = schemas[binding.dependency]
                action = ActionExecutionService(
                    self.sessions, self.authorizer, session=s
                ).definition(schema, binding.action_id)
                parameters = {v.id: v for v in action.parameters}
                if set(binding.parameters) - parameters.keys() or any(
                    v.required and v.id not in binding.parameters for v in action.parameters
                ):
                    raise ValueError("Action parameter mismatch")
                for key, kind in binding.parameter_types.items():
                    if key not in parameters or parameters[key].data_type != kind:
                        raise ValueError("Action type mismatch")
                    value = binding.parameters[key]
                    if value.kind == "literal":
                        parameters[key].validate_value(value.value)
                    elif value.kind == "state":
                        if value.state not in states or states[value.state].data_type != kind:
                            raise ValueError("State parameter type mismatch")
                    elif value.kind == "selected":
                        selected_type = selection_types.get(value.state or "")
                        if selected_type is None:
                            raise ValueError("Selection has no object source")
                        field = (
                            selected_type.primary_key if value.property == "$id" else value.property
                        )
                        actual = (
                            "integer"
                            if field == "$version"
                            else next(
                                (v.data_type for v in selected_type.properties if v.id == field),
                                None,
                            )
                        )
                        if actual != kind:
                            raise ValueError("Selection parameter type mismatch")
        except (ApplicationError, ValueError, KeyError, StopIteration):
            # Never echo inaccessible names, schemas, IDs or property values.
            result.diagnostics = [
                Diagnostic(
                    code="dependency_unavailable_or_incompatible",
                    message="Dependency unavailable, unauthorized or incompatible; reselect it",
                )
            ]
            result.valid = False
        return result

    def validate(self, p: Principal, key: UUID, doc: Document) -> Validation:
        with self.scope(p) as s:
            self.application(s, p, key)
            return self.validate_in(s, p, doc)

    def draft(self, p: Principal, key: UUID) -> Draft | None:
        with self.scope(p) as s:
            self.application(s, p, key, True)
            row = s.get(ApplicationDraft, (p.tenant_id, key, p.principal_id))
            if row is None:
                return None
            doc = Document.model_validate(row.document)
            self.references(s, p, doc, active=False)
            return Draft(revision=row.revision, document=doc)

    def save(self, p: Principal, key: UUID, body: Save) -> Draft:
        with self.scope(p) as s:
            self.application(s, p, key, True)
            self.references(s, p, body.document, active=False)
            row = s.get(ApplicationDraft, (p.tenant_id, key, p.principal_id), with_for_update=True)
            if (row.revision if row else 0) != body.expected_revision:
                raise ApplicationError(
                    "draft_conflict", "Draft changed; reopen and recover local edits", 409
                )
            if row is None:
                row = ApplicationDraft(
                    tenant_id=p.tenant_id,
                    application_id=key,
                    actor_id=p.principal_id,
                    revision=1,
                    document=body.document.model_dump(mode="json", by_alias=True),
                )
                s.add(row)
            else:
                row.revision += 1
                row.document = body.document.model_dump(mode="json", by_alias=True)
            self.audit(s, p, "application_draft_save", key)
            s.flush()
            return Draft(revision=row.revision, document=body.document)

    def publish(self, p: Principal, key: UUID, body: Publish) -> Published:
        with (
            self.scope(p) as s,
            action_deadline(
                s,
                time.monotonic() + 5,
                code="application_publication_timeout",
                message="Publication exceeded 5 seconds",
            ),
        ):
            s.execute(text("SET LOCAL statement_timeout = '5s'"))
            self.application(s, p, key, True)
            draft = s.get(
                ApplicationDraft, (p.tenant_id, key, p.principal_id), with_for_update=True
            )
            if draft is None or draft.revision != body.expected_revision:
                raise ApplicationError(
                    "draft_conflict", "Save and reload the current draft before publishing", 409
                )
            doc = Document.model_validate(draft.document)
            if not self.validate_in(s, p, doc).valid:
                raise ApplicationError(
                    "application_invalid", "Resolve validation diagnostics before publication", 422
                )
            old = s.scalar(
                select(ApplicationVersion).where(
                    ApplicationVersion.tenant_id == p.tenant_id,
                    ApplicationVersion.application_id == key,
                    ApplicationVersion.digest == doc.digest(),
                )
            )
            if old:
                return Published.model_validate(old)
            sequence = (
                s.scalar(
                    select(func.max(ApplicationVersion.sequence)).where(
                        ApplicationVersion.tenant_id == p.tenant_id,
                        ApplicationVersion.application_id == key,
                    )
                )
                or 0
            )
            if sequence >= 1000:
                raise conflict("Application publication history limit reached")
            row = ApplicationVersion(
                tenant_id=p.tenant_id,
                application_id=key,
                id=uuid4(),
                sequence=sequence + 1,
                format_version=1,
                document=doc.model_dump(mode="json", by_alias=True),
                digest=doc.digest(),
                manifest=[d.model_dump(mode="json") for d in doc.dependencies],
                created_by=p.principal_id,
            )
            s.add(row)
            s.flush()
            self.audit(s, p, "application_publish", row.id)
            return Published.model_validate(row)

    def version_in(self, s: Session, p: Principal, key: UUID, version: UUID) -> Published:
        self.application(s, p, key)
        row = s.get(ApplicationVersion, (p.tenant_id, key, version))
        if row is None:
            raise missing("Application version")
        view = Published.model_validate(row)
        if not self.validate_in(s, p, view.document).valid:
            raise ApplicationError(
                "dependency_unavailable",
                "Application dependencies are unavailable or incompatible",
                409,
            )
        return view

    def version(self, p: Principal, key: UUID, version: UUID) -> Published:
        with self.scope(p) as s:
            return self.version_in(s, p, key, version)

    def versions(
        self, p: Principal, key: UUID, limit: int = 50, offset: int = 0
    ) -> list[Published]:
        page(limit, offset)
        with self.scope(p) as s:
            self.application(s, p, key)
            ids = s.scalars(
                select(ApplicationVersion.id)
                .where(
                    ApplicationVersion.tenant_id == p.tenant_id,
                    ApplicationVersion.application_id == key,
                )
                .order_by(ApplicationVersion.sequence.desc())
                .limit(limit)
                .offset(offset)
            )
            return [self.version_in(s, p, key, ident) for ident in ids]

    @staticmethod
    def value(value: Value, state: dict[str, Any]) -> Any:
        if value.kind == "literal":
            return value.value
        raw = state.get(value.state or "")
        if value.kind == "selected":
            if not isinstance(raw, dict):
                return None
            if value.property == "$id":
                return raw.get("object_id")
            if value.property == "$version":
                return raw.get("version")
            props = raw.get("properties")
            return props.get(value.property) if isinstance(props, dict) else None
        return raw

    def query(
        self, p: Principal, key: UUID, version: UUID, body: RuntimeQuery
    ) -> QueryPage | AggregateResult:
        with self.scope(p) as s:
            doc = self.version_in(s, p, key, version).document
            source = next((v for v in doc.sources if v.id == body.source_id), None)
            if source is None:
                raise missing("Data source")
            dep = next(d for d in doc.dependencies if d.id == source.dependency)
            filters: list[dict[str, Any]] = []
            if source.query.filter:
                filters.append(source.query.filter.model_dump(mode="json", by_alias=True))
            for prop, binding in source.filters.items():
                value = self.value(binding, body.state)
                if value is not None and value != "":
                    filters.append({"property": prop, "operator": "eq", "value": value})
                elif binding.kind == "selected":
                    # Empty selections never turn into unrestricted queries.
                    raise ApplicationError("selection_required", "Select an object first", 422)
            filtering = {"and": filters} if filters else None
            queries = QueryService(self.sessions, self.authorizer, self.cursors, session=s)
            if source.aggregate:
                request = source.aggregate.model_dump(mode="json", by_alias=True)
                existing = request.get("filter")
                request["filter"] = (
                    {"and": [existing, filtering]}
                    if existing and filtering
                    else existing or filtering
                )
                return queries.aggregate(
                    p, dep.ontology_id, AggregateRequest.model_validate(request)
                )
            data = source.query.model_dump(mode="json", by_alias=True)
            data.update(filter=filtering, cursor=body.cursor)
            if body.order_by is not None:
                data["order_by"] = [sort.model_dump() for sort in body.order_by]
            return queries.query(p, dep.ontology_id, QueryRequest.model_validate(data))

    def action(
        self,
        p: Principal,
        key: UUID,
        version: UUID,
        binding_id: str,
        body: ExecuteRequest,
        preview: bool,
    ) -> ActionResult:
        with self.scope(p) as s:
            # Action service takes the write lock first, avoiding reader-to-writer upgrade races.
            self.application(s, p, key)
            raw = s.get(ApplicationVersion, (p.tenant_id, key, version))
            if raw is None:
                raise missing("Application version")
            definition = Document.model_validate(raw.document)
            for dep in sorted(definition.dependencies, key=lambda d: d.ontology_id):
                self.ontology(s, p, dep.ontology_id, write=True)
            doc = self.version_in(s, p, key, version).document
            binding = next((a for a in doc.actions if a.id == binding_id), None)
            if binding is None:
                raise missing("Action binding")
            dep = next(d for d in doc.dependencies if d.id == binding.dependency)
            actions = ActionExecutionService(self.sessions, self.authorizer, session=s)
            if preview:
                return actions.preview(
                    p, dep.ontology_id, binding.action_id, ActionRequest(parameters=body.parameters)
                )
            return actions.execute(p, dep.ontology_id, binding.action_id, body)
