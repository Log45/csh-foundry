"""Inert action interpreter over the governed Phase 1 services in one unit of work."""

import hashlib
import json
import time
from collections.abc import Callable
from uuid import UUID, uuid4

from ontology_schema.models import (
    ActionTypeDefinition,
    ActionValue,
    LiteralValue,
    ObjectValue,
    OntologyDefinition,
    ParameterValue,
)
from pydantic import JsonValue
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from ontology_platform.actions.contracts import (
    ActionRequest,
    ActionResult,
    Change,
    ExecuteRequest,
    ExecutionView,
    HistoryPage,
)
from ontology_platform.actions.deadline import action_deadline
from ontology_platform.contracts import CreateObject, LinkInput, ObjectPatch, ObjectView
from ontology_platform.db.governance import GovernedService, missing
from ontology_platform.db.models import ActionExecution, AuditEvent, EditOverlay, Link, OutboxEvent
from ontology_platform.errors import ApplicationError
from ontology_platform.metadata.storage import active_definition, definition_of, version_row
from ontology_platform.objects.relationships import link_type
from ontology_platform.objects.service import ObjectService, resource
from ontology_platform.objects.validation import object_type, validate_properties
from ontology_platform.security.interfaces import Principal


def canonical(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def invalid(message: str) -> ApplicationError:
    return ApplicationError("invalid_action", message, 422)


class ActionExecutionService(GovernedService):
    def definition(self, schema: OntologyDefinition, action_id: str) -> ActionTypeDefinition:
        action = next((a for a in schema.action_types if a.id == action_id), None)
        if action is None:
            raise missing("Active action")
        if not action.operations or any(
            o.binding is None and o.source is None for o in action.operations
        ):
            raise invalid("Legacy target-only declarations are not executable")
        if len(action.canonical_json().encode()) > 65536:
            raise invalid("Action definition exceeds 64 KiB")
        return action

    @staticmethod
    def parameters(action: ActionTypeDefinition, request: ActionRequest) -> dict[str, JsonValue]:
        definitions = {p.id: p for p in action.parameters}
        if request.parameters.keys() - definitions.keys():
            raise invalid("Unknown action parameter")
        result = dict(request.parameters)
        try:
            for name, typed in definitions.items():
                if name not in result:
                    if typed.has_default or typed.default is not None:
                        result[name] = typed.default
                    elif typed.required:
                        raise ValueError("Missing required parameter")
                    else:
                        continue
                typed.validate_value(result[name])
        except ValueError as exc:
            raise invalid("Action parameter validation failed") from exc
        return result

    def _run(
        self,
        session: Session,
        principal: Principal,
        ontology_id: str,
        schema: OntologyDefinition,
        action: ActionTypeDefinition,
        parameters: dict[str, JsonValue],
        budget: Callable[[], None],
    ) -> list[Change]:
        objects = ObjectService(self.sessions, self.authorizer, session=session, record_edits=False)
        bindings: dict[str, tuple[str, str]] = {}
        changes: list[Change] = []

        def identity(binding: str | None) -> tuple[str, str]:
            if binding not in bindings:
                raise invalid("Unresolved object binding")
            assert binding is not None
            return bindings[binding]

        def read(binding: str | None) -> ObjectView:
            typed, key = identity(binding)
            return objects.get(principal, ontology_id, typed, key)

        def permission(binding: str | None, prop: str, operation: str = "property:read") -> None:
            typed, key = identity(binding)
            self.authorizer.require(
                principal,
                operation,
                resource(principal, ontology_id, typed, key) + f"/properties/{prop}",
            )

        def value(ref: ActionValue | None) -> JsonValue:
            if isinstance(ref, LiteralValue):
                return ref.value
            if isinstance(ref, ParameterValue):
                if ref.parameter not in parameters:
                    raise invalid("Referenced optional parameter is absent")
                return parameters[ref.parameter]
            if isinstance(ref, ObjectValue):
                if ref.property is None:
                    return identity(ref.binding)[1]
                permission(ref.binding, ref.property)
                row = read(ref.binding)
                if ref.property not in row.properties:
                    raise invalid("Referenced property is absent")
                return row.properties[ref.property]
            raise invalid("Missing value reference")

        def revision(ref: ActionValue | None) -> int:
            result = value(ref)
            if type(result) is not int or result < 1:
                raise invalid("Expected revision requires a positive integer")
            return result

        def key(ref: ActionValue | None) -> str:
            result = value(ref)
            if not isinstance(result, str) or not result:
                raise invalid("Object identity requires a nonempty canonical string")
            return result

        for parameter in action.parameters:
            if parameter.object_type_id is not None and parameter.id in parameters:
                budget()
                identity_value = parameters[parameter.id]
                if not isinstance(identity_value, str):
                    raise invalid("Object identity must be a canonical string")
                objects.get(principal, ontology_id, parameter.object_type_id, identity_value)
        for item in action.bindings:
            budget()
            bindings[item.id] = (item.object_type, key(item.object_id))
            binding_type, object_id = identity(item.id)
            # Even absence checks require permission to observe the identity.
            self.authorizer.require(
                principal, "object:read", resource(principal, ontology_id, binding_type, object_id)
            )
        for condition in action.preconditions:
            budget()
            ok = False
            if condition.type == "PARAMETER_PRESENT":
                ok = condition.parameter in parameters
            elif condition.type.startswith("LINK_"):
                typed = link_type(schema, condition.link or "")
                self.authorizer.require(
                    principal, "link:read", f"{principal.tenant_id}/{ontology_id}/links/{typed.id}"
                )
                source, target = read(condition.source), read(condition.target)
                edge = session.get(
                    Link,
                    (
                        principal.tenant_id,
                        ontology_id,
                        typed.id,
                        typed.source_type,
                        source.object_id,
                        typed.target_type,
                        target.object_id,
                    ),
                )
                ok = (edge is not None) == (condition.type == "LINK_EXISTS")
            else:
                try:
                    row = read(condition.binding)
                except ApplicationError as exc:
                    if exc.code != "not_found":
                        raise
                    row = None
                if condition.type in {"EXISTS", "NOT_EXISTS"}:
                    ok = (row is not None) == (condition.type == "EXISTS")
                elif row is not None and condition.type == "REVISION_EQUALS":
                    ok = row.version == revision(condition.value)
                elif row is not None and condition.property is not None:
                    permission(condition.binding, condition.property)
                    ok = condition.property in row.properties and canonical(
                        row.properties[condition.property]
                    ) == canonical(value(condition.value))
            if not ok:
                raise ApplicationError(
                    "precondition_failed", "Current state violates action precondition", 409
                )
        for operation in action.operations:
            budget()
            if operation.type.endswith("LINK"):
                typed = link_type(schema, operation.target)
                source, target = read(operation.source), read(operation.destination)
                request = LinkInput(
                    link_type_id=typed.id,
                    source_object_type_id=source.object_type_id,
                    source_object_id=source.object_id,
                    target_object_type_id=target.object_type_id,
                    target_object_id=target.object_id,
                )
                if operation.type == "CREATE_LINK":
                    objects.create_link(principal, ontology_id, request)
                else:
                    objects.delete_link(principal, ontology_id, request)
                changes.append(
                    Change(
                        operation=operation.type,
                        object_type=source.object_type_id,
                        object_id=source.object_id,
                        link=typed.id,
                        target_type=target.object_type_id,
                        target_id=target.object_id,
                    )
                )
            else:
                properties = {name: value(ref) for name, ref in operation.properties.items()}
                if operation.type == "CREATE_OBJECT":
                    assert operation.binding is not None
                    object_id = key(operation.object_id)
                    bindings[operation.binding] = (operation.target, object_id)
                    properties = validate_properties(
                        object_type(schema, operation.target), object_id, properties, defaults=True
                    )
                    before = None
                else:
                    current = read(operation.binding)
                    object_id, before = current.object_id, current.version
                    if operation.type == "DELETE_OBJECT":
                        properties = dict(current.properties)
                for prop in properties:
                    permission(operation.binding, prop, "property:update")
                after: int | None = None
                if operation.type == "CREATE_OBJECT":
                    after = objects.create(
                        principal,
                        ontology_id,
                        CreateObject(
                            object_type_id=operation.target,
                            object_id=object_id,
                            properties=properties,
                        ),
                    ).version
                elif operation.type == "UPDATE_OBJECT":
                    after = objects.patch(
                        principal,
                        ontology_id,
                        operation.target,
                        object_id,
                        ObjectPatch(
                            expected_version=revision(operation.expected_version),
                            properties=properties,
                        ),
                    ).version
                else:
                    objects.delete(
                        principal,
                        ontology_id,
                        operation.target,
                        object_id,
                        revision(operation.expected_version),
                    )
                changes.append(
                    Change(
                        operation=operation.type,
                        object_type=operation.target,
                        object_id=object_id,
                        previous_revision=before,
                        new_revision=after,
                        properties=sorted(properties),
                    )
                )
            session.flush()
        budget()
        return changes

    def _perform(
        self,
        principal: Principal,
        ontology_id: str,
        action_id: str,
        request: ActionRequest,
        *,
        preview: bool,
    ) -> ActionResult:
        started = time.monotonic()
        try:
            with (
                self.operation(
                    principal, "action:invoke", f"{ontology_id}/actions/{action_id}"
                ) as session,
                action_deadline(session, started + 3),
            ):

                def budget() -> None:
                    remaining = 3 - (time.monotonic() - started)
                    if remaining <= 0:
                        raise ApplicationError(
                            "action_timeout", "Action exceeded its 3 second budget", 503
                        )
                    session.execute(
                        text("SELECT set_config('statement_timeout', :budget, true)"),
                        {"budget": str(max(1, int(remaining * 1000)))},
                    )

                budget()
                ontology = self.ontology(session, principal, ontology_id, write=True)
                key_hash = None
                if not preview and isinstance(request, ExecuteRequest):
                    key_hash = digest(request.idempotency_key)
                    existing = session.scalar(
                        select(ActionExecution).where(
                            ActionExecution.tenant_id == principal.tenant_id,
                            ActionExecution.ontology_id == ontology_id,
                            ActionExecution.principal_id == principal.principal_id,
                            ActionExecution.key_hash == key_hash,
                        )
                    )
                    if existing:
                        self.authorizer.require(
                            principal,
                            "action:history",
                            f"{principal.tenant_id}/{ontology_id}/actions/executions/{existing.id}",
                        )
                        original_schema = definition_of(
                            version_row(session, ontology, existing.schema_version)
                        )
                        try:
                            original_action = self.definition(original_schema, action_id)
                            original_parameters = self.parameters(original_action, request)
                            retry_hash = digest([action_id, original_parameters])
                        except ApplicationError as exc:
                            raise ApplicationError(
                                "idempotency_conflict", "Key belongs to a different request", 409
                            ) from exc
                        if existing.request_hash != retry_hash:
                            raise ApplicationError(
                                "idempotency_conflict", "Key belongs to a different request", 409
                            )
                        return ActionResult.model_validate(existing.result)
                schema = active_definition(session, ontology)
                action = self.definition(schema, action_id)
                parameters = self.parameters(action, request)
                request_hash = digest([action_id, parameters])
                action_version = digest(action.model_dump(mode="json"))
                # Same real service validation for preview; UUID IDs have no sequence side effects.
                # Roll back even on success. No durable records are staged here.
                if preview:
                    savepoint = session.begin_nested()
                    try:
                        changes = self._run(
                            session, principal, ontology_id, schema, action, parameters, budget
                        )
                    finally:
                        savepoint.rollback()
                    return ActionResult(
                        action_id=action_id,
                        action_version=action_version,
                        schema_version=schema.version,
                        changes=changes,
                        advisory=True,
                    )
                execution_id = uuid4()
                changes = self._run(
                    session, principal, ontology_id, schema, action, parameters, budget
                )
                result = ActionResult(
                    execution_id=execution_id,
                    action_id=action_id,
                    action_version=action_version,
                    schema_version=schema.version,
                    changes=changes,
                )
                assert key_hash is not None
                execution = ActionExecution(
                    tenant_id=principal.tenant_id,
                    ontology_id=ontology_id,
                    id=execution_id,
                    action_id=action_id,
                    action_version=action_version,
                    schema_version=schema.version,
                    principal_id=principal.principal_id,
                    key_hash=key_hash,
                    request_hash=request_hash,
                    fingerprint=digest(
                        [
                            str(principal.tenant_id),
                            principal.principal_id,
                            ontology_id,
                            action_id,
                            action_version,
                            schema.version,
                            parameters,
                        ]
                    ),
                    result=result.model_dump(mode="json"),
                )
                session.add(execution)
                session.flush()
                for change in changes:
                    session.add(
                        AuditEvent(
                            tenant_id=principal.tenant_id,
                            ontology_id=ontology_id,
                            id=uuid4(),
                            execution_id=execution_id,
                            actor=principal.principal_id,
                            object_type_id=change.object_type,
                            object_id=change.object_id,
                            operation=change.operation,
                            details=change.model_dump(mode="json"),
                        )
                    )
                    if change.operation.endswith("OBJECT"):
                        self._overlays(
                            session, principal, ontology_id, schema.version, execution_id, change
                        )
                session.add(
                    OutboxEvent(
                        tenant_id=principal.tenant_id,
                        ontology_id=ontology_id,
                        id=uuid4(),
                        execution_id=execution_id,
                        payload={
                            "execution_id": str(execution_id),
                            "action_id": action_id,
                            "schema_version": schema.version,
                        },
                    )
                )
                session.flush()
                budget()
                return result
        except DBAPIError as exc:
            raise ApplicationError(
                "action_database_error", "Action rolled back; retry with the same key", 503
            ) from exc

    @staticmethod
    def _overlays(
        session: Session,
        principal: Principal,
        ontology_id: str,
        schema_version: str,
        execution_id: UUID,
        change: Change,
    ) -> None:
        from sqlalchemy import delete

        from ontology_platform.db.models import Object

        if change.operation == "DELETE_OBJECT":
            session.execute(
                delete(EditOverlay).where(
                    EditOverlay.tenant_id == principal.tenant_id,
                    EditOverlay.ontology_id == ontology_id,
                    EditOverlay.object_type_id == change.object_type,
                    EditOverlay.object_id == change.object_id,
                )
            )
            return
        row = session.get(
            Object, (principal.tenant_id, ontology_id, change.object_type, change.object_id)
        )
        if row is None:
            return  # A later operation deleted this object; audit still records both operations.
        for prop in change.properties:
            if prop not in row.properties:
                continue  # A later delete/recreate omitted an optional property.
            key = (principal.tenant_id, ontology_id, change.object_type, change.object_id, prop)
            overlay = session.get(EditOverlay, key)
            if overlay is None:
                overlay = EditOverlay(
                    tenant_id=principal.tenant_id,
                    ontology_id=ontology_id,
                    object_type_id=change.object_type,
                    object_id=change.object_id,
                    property_id=prop,
                    source_value=None,
                )
                session.add(overlay)
            overlay.updated_by = principal.principal_id
            overlay.owner, overlay.value = "action", row.properties[prop]
            overlay.schema_version, overlay.revision = schema_version, row.version
            overlay.execution_id = execution_id

    def preview(
        self, principal: Principal, ontology_id: str, action_id: str, request: ActionRequest
    ) -> ActionResult:
        return self._perform(principal, ontology_id, action_id, request, preview=True)

    def execute(
        self, principal: Principal, ontology_id: str, action_id: str, request: ExecuteRequest
    ) -> ActionResult:
        return self._perform(principal, ontology_id, action_id, request, preview=False)

    def history(
        self, principal: Principal, ontology_id: str, limit: int = 50, offset: int = 0
    ) -> HistoryPage:
        if not 1 <= limit <= 100 or not 0 <= offset <= 10000:
            raise invalid("Invalid history page")
        with self.operation(
            principal, "action:history", f"{ontology_id}/actions/executions"
        ) as session:
            self.ontology(session, principal, ontology_id)
            rows = list(
                session.scalars(
                    select(ActionExecution)
                    .where(
                        ActionExecution.tenant_id == principal.tenant_id,
                        ActionExecution.ontology_id == ontology_id,
                    )
                    .order_by(ActionExecution.created_at.desc(), ActionExecution.id)
                    .offset(offset)
                    .limit(limit + 1)
                )
            )
            for row in rows[:limit]:
                self.authorizer.require(
                    principal,
                    "action:history",
                    f"{principal.tenant_id}/{ontology_id}/actions/executions/{row.id}",
                )
            return HistoryPage(
                items=[ExecutionView.model_validate(row) for row in rows[:limit]],
                has_more=len(rows) > limit,
            )

    def get_execution(
        self, principal: Principal, ontology_id: str, execution_id: UUID
    ) -> ExecutionView:
        with self.operation(
            principal, "action:history", f"{ontology_id}/actions/executions/{execution_id}"
        ) as session:
            row = session.get(ActionExecution, (principal.tenant_id, ontology_id, execution_id))
            if row is None:
                raise missing("Execution")
            return ExecutionView.model_validate(row)

    def audit(self, principal: Principal, ontology_id: str, execution_id: UUID) -> list[Change]:
        with self.operation(
            principal, "action:audit", f"{ontology_id}/actions/executions/{execution_id}/audit"
        ) as session:
            if (
                session.get(ActionExecution, (principal.tenant_id, ontology_id, execution_id))
                is None
            ):
                raise missing("Execution")
            return [
                Change.model_validate(row.details)
                for row in session.scalars(
                    select(AuditEvent)
                    .where(
                        AuditEvent.tenant_id == principal.tenant_id,
                        AuditEvent.ontology_id == ontology_id,
                        AuditEvent.execution_id == execution_id,
                    )
                    .order_by(AuditEvent.created_at, AuditEvent.id)
                    .limit(64)
                )
            ]
