"""PostgreSQL schedules and atomic trigger receipt + execution-job admission."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Text, exists, func, select
from sqlalchemy.orm import Session

from ontology_platform.automations.contracts import (
    AutomationDefinition,
    Enable,
    ReceiptView,
    ScheduleView,
    Trigger,
)
from ontology_platform.branching.service import page
from ontology_platform.db.governance import missing
from ontology_platform.db.models import (
    AutomationReceipt,
    AutomationState,
    ExecutionJob,
    GovernedDefinition,
    OutboxEvent,
    Resource,
)
from ontology_platform.db.session import clock
from ontology_platform.errors import ApplicationError
from ontology_platform.functions.contracts import (
    FunctionDefinition,
    GovernedDefinitionView,
    GSettings,
    Invoke,
    typed,
)
from ontology_platform.functions.service import FunctionService
from ontology_platform.projects.service import conflict
from ontology_platform.security.interfaces import Principal


def internal_actor(data: dict[str, Any], seconds: int = 3600) -> Principal:
    actor = Principal.model_validate(data)
    if actor.authentication_method in {"oidc", "test"}:
        actor = actor.model_copy(
            update={"expires_at": datetime.now(UTC) + timedelta(seconds=seconds)}
        )
    return actor


def next_instant(trigger: Trigger, now: datetime) -> datetime | None:
    if trigger.kind == "interval":
        assert trigger.interval_seconds is not None
        return now + timedelta(seconds=trigger.interval_seconds)
    if trigger.kind == "daily":
        assert trigger.hour is not None and trigger.minute is not None
        instant = now.astimezone(UTC).replace(
            hour=trigger.hour, minute=trigger.minute, second=0, microsecond=0
        )
        return instant if instant > now else instant + timedelta(days=1)
    return None


class AutomationService(FunctionService):
    resource_kind = "AUTOMATION"

    def functions(self, s: Session | None = None) -> FunctionService:
        svc = FunctionService(self.sessions, self.authorizer, self.settings, self.store)
        svc.transaction_session = s
        return svc

    def validate_target(
        self, s: Session, p: Principal, data: dict[str, Any]
    ) -> AutomationDefinition:
        spec = AutomationDefinition.model_validate(data)
        svc = self.functions(s)
        svc.artifact(s, p, spec.function_id, True)
        target = svc.governed_definition(s, p, spec.function_id, spec.function_definition_id)
        definition = FunctionDefinition.model_validate(target.specification)
        try:
            typed(spec.inputs, definition.input_schema, GSettings().input_bytes)
        except (ValueError, OverflowError) as exc:
            raise ApplicationError(
                "invalid_input", "Automation bindings violate target contract", 422
            ) from exc
        if spec.trigger.ontology_resource_id:
            resource = self.resource(s, p, spec.trigger.ontology_resource_id)
            if resource.resource_type != "ONTOLOGY_VERSION":
                raise conflict("Event source must be an authorized ontology version")
            self.authorizer.require(
                p, "action:history", f"{p.tenant_id}/{resource.ontology_id}/actions/executions"
            )
        return spec

    def publish_automation(
        self, p: Principal, key: UUID, spec: AutomationDefinition
    ) -> GovernedDefinitionView:
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            self.validate_target(s, p, spec.model_dump(mode="json"))
            return self.publish_spec(s, p, key, spec.model_dump(mode="json"))

    def state(self, s: Session, p: Principal, key: UUID, write: bool = False) -> AutomationState:
        self.artifact(s, p, key, write)
        row = s.get(AutomationState, (p.tenant_id, key), with_for_update=write)
        if row is None:
            raise missing("Automation activation")
        return row

    def enable(self, p: Principal, key: UUID, body: Enable) -> ScheduleView:
        if p.authentication_method == "job":
            raise ApplicationError("forbidden", "Job grants cannot change schedule activation", 403)
        with self.scope(p) as s:
            self.artifact(s, p, key, True)
            definition = self.governed_definition(s, p, key, body.definition_id)
            spec = AutomationDefinition.model_validate(definition.specification)
            row = s.get(AutomationState, (p.tenant_id, key), with_for_update=True)
            if row is not None and row.owner != p.principal_id:
                raise ApplicationError(
                    "forbidden", "Only the bound owner can change activation", 403
                )
            if body.enabled:
                self.validate_target(s, p, definition.specification)
                count = (
                    s.scalar(
                        select(func.count())
                        .select_from(AutomationState)
                        .where(
                            AutomationState.tenant_id == p.tenant_id,
                            AutomationState.enabled.is_(True),
                            AutomationState.automation_id != key,
                        )
                    )
                    or 0
                )
                resource = self.artifact(s, p, key, True)
                project_count = (
                    s.scalar(
                        select(func.count())
                        .select_from(AutomationState)
                        .join(
                            Resource,
                            (Resource.tenant_id == AutomationState.tenant_id)
                            & (Resource.id == AutomationState.automation_id),
                        )
                        .where(
                            AutomationState.tenant_id == p.tenant_id,
                            AutomationState.enabled.is_(True),
                            AutomationState.automation_id != key,
                            Resource.project_id == resource.project_id,
                        )
                    )
                    or 0
                )
                if project_count >= GSettings().project_schedules:
                    raise conflict("Project automation limit reached")
                if count >= GSettings().schedules:
                    raise conflict("Tenant automation limit reached")
            # Re-enabling the same active version is idempotent, not a schedule reset.
            if (
                row is not None
                and row.enabled == body.enabled
                and row.definition_id == body.definition_id
            ):
                return ScheduleView.model_validate(row)
            now = clock(s)
            if row is None:
                row = AutomationState(
                    tenant_id=p.tenant_id,
                    automation_id=key,
                    definition_id=definition.id,
                    activation_id=uuid4(),
                    owner=p.principal_id,
                    principal=p.model_dump(mode="json"),
                    event_time=now,
                    event_id=UUID(int=0),
                )
                s.add(row)
            row.definition_id, row.enabled = definition.id, body.enabled
            row.activation_id = uuid4()
            row.principal, row.last_error = p.model_dump(mode="json"), None
            row.next_run_at = next_instant(spec.trigger, now) if body.enabled else None
            row.event_time, row.event_id = now, UUID(int=0)
            self.audit(s, p, "automation_enable" if body.enabled else "automation_disable", key)
            s.flush()
            return ScheduleView.model_validate(row)

    def schedule(self, p: Principal, key: UUID) -> ScheduleView:
        with self.scope(p) as s:
            return ScheduleView.model_validate(self.state(s, p, key))

    def dispatch(
        self,
        s: Session,
        p: Principal,
        row: AutomationState,
        dedup: str,
        instant: datetime,
        kind: str,
    ) -> ReceiptView:
        if not row.enabled or row.owner != p.principal_id:
            raise conflict("Automation disabled or owner mismatch")
        self.artifact(s, p, row.automation_id, True)
        definition = self.governed_definition(s, p, row.automation_id, row.definition_id)
        spec = self.validate_target(s, p, definition.specification)
        previous = s.scalar(
            select(AutomationReceipt).where(
                AutomationReceipt.tenant_id == p.tenant_id,
                AutomationReceipt.automation_id == row.automation_id,
                AutomationReceipt.dedup_key == dedup,
            )
        )
        if previous:
            return ReceiptView.model_validate(previous)
        recent = (
            s.scalar(
                select(func.count())
                .select_from(AutomationReceipt)
                .where(
                    AutomationReceipt.tenant_id == p.tenant_id,
                    AutomationReceipt.created_at >= clock(s) - timedelta(seconds=60),
                )
            )
            or 0
        )
        if recent >= GSettings().dispatch_per_minute:
            raise ApplicationError("queue_capacity", "Automation dispatch rate exceeded", 503)
        count = (
            s.scalar(
                select(func.count())
                .select_from(AutomationReceipt)
                .where(
                    AutomationReceipt.tenant_id == p.tenant_id,
                    AutomationReceipt.automation_id == row.automation_id,
                )
            )
            or 0
        )
        if count >= GSettings().history:
            raise conflict("Retained automation history limit reached")
        pending = (
            s.scalar(
                select(func.count())
                .select_from(ExecutionJob)
                .where(
                    ExecutionJob.tenant_id == p.tenant_id,
                    ExecutionJob.state.in_(["QUEUED", "ADMITTED", "RUNNING", "CANCELLING"]),
                )
            )
            or 0
        )
        if pending >= GSettings().backlog:
            raise ApplicationError("queue_capacity", "Automation backlog full", 503)
        run_key = hashlib.sha256(f"{row.automation_id}:{dedup}".encode()).hexdigest()
        job = self.functions(s).admit(
            s,
            p,
            spec.function_id,
            Invoke(
                definition_id=spec.function_definition_id,
                inputs=spec.inputs,
                idempotency_key=run_key,
            ),
            {
                "resource_id": str(row.automation_id),
                "definition_id": str(row.definition_id),
                "activation_id": str(row.activation_id),
            },
        )
        receipt = AutomationReceipt(
            tenant_id=p.tenant_id,
            automation_id=row.automation_id,
            id=uuid4(),
            definition_id=row.definition_id,
            dedup_key=dedup,
            trigger_kind=kind,
            trigger_at=instant,
            job_id=job.id,
        )
        s.add(receipt)
        self.audit(s, p, "automation_dispatch", receipt.id)
        s.flush()
        return ReceiptView.model_validate(receipt)

    def manual(self, p: Principal, key: UUID, dedup: str) -> ReceiptView:
        with self.scope(p) as s:
            row = self.state(s, p, key, True)
            definition = self.governed_definition(s, p, key, row.definition_id)
            if (
                AutomationDefinition.model_validate(definition.specification).trigger.kind
                != "manual"
            ):
                raise conflict("Manual trigger requires a manual definition")
            return self.dispatch(
                s,
                p,
                row,
                "manual:" + hashlib.sha256(dedup.encode()).hexdigest(),
                clock(s),
                "manual",
            )

    def history_receipts(
        self, p: Principal, key: UUID, limit: int, offset: int
    ) -> list[ReceiptView]:
        page(limit, offset)
        with self.scope(p) as s:
            self.artifact(s, p, key)
            rows = s.scalars(
                select(AutomationReceipt)
                .where(
                    AutomationReceipt.tenant_id == p.tenant_id,
                    AutomationReceipt.automation_id == key,
                )
                .order_by(AutomationReceipt.created_at.desc(), AutomationReceipt.id)
                .limit(limit)
                .offset(offset)
            )
            visible = []
            for row in rows:
                try:
                    definition = self.governed_definition(s, p, key, row.definition_id)
                    self.validate_target(s, p, definition.specification)
                except ApplicationError as exc:
                    if exc.status_code in {403, 404}:
                        continue
                    raise
                visible.append(ReceiptView.model_validate(row))
            return visible

    def tick(self, executor: Principal | None = None) -> int:
        from ontology_platform.security.service import PlatformAuthorizer

        if isinstance(self.authorizer, PlatformAuthorizer):
            if executor is None or executor.principal_type != "service":
                raise ApplicationError(
                    "worker_identity_required", "Scheduler service required", 403
                )
            self.authorizer.require(
                executor, "automation:dispatch", f"{executor.tenant_id}/projects"
            )
        # Candidate discovery is read-only and takes no locks before security/tenant locks.
        with self.sessions() as s:
            candidates = list(
                s.scalars(
                    select(AutomationState)
                    .join(
                        GovernedDefinition,
                        (GovernedDefinition.tenant_id == AutomationState.tenant_id)
                        & (GovernedDefinition.resource_id == AutomationState.automation_id)
                        & (GovernedDefinition.id == AutomationState.definition_id),
                    )
                    .where(
                        AutomationState.enabled.is_(True),
                        *([AutomationState.tenant_id == executor.tenant_id] if executor else []),
                        GovernedDefinition.specification["trigger"]["kind"].astext != "manual",
                    )
                    .order_by(
                        AutomationState.checked_at,
                        AutomationState.automation_id,
                    )
                    .limit(GSettings().schedules)
                )
            )
            data = [
                (r.tenant_id, r.automation_id, r.activation_id, dict(r.principal))
                for r in candidates
            ]
        dispatched = 0
        for tenant, key, activation, principal in data:
            if dispatched >= GSettings().dispatch_batch:
                break
            actor = internal_actor(principal)
            try:
                with self.scope(actor) as s:
                    if executor is not None:
                        self.authorizer.require(
                            executor, "automation:dispatch", f"{tenant}/projects"
                        )
                        self.artifact(s, executor, key, True)
                    row = self.state(s, actor, key, True)
                    if not row.enabled:
                        continue
                    activation = row.activation_id
                    if row.owner != actor.principal_id or row.tenant_id != actor.tenant_id:
                        raise ApplicationError("forbidden", "Schedule owner mismatch", 403)
                    definition = self.governed_definition(s, actor, key, row.definition_id)
                    spec = self.validate_target(s, actor, definition.specification)
                    if executor is not None:
                        self.validate_target(s, executor, definition.specification)
                    now = clock(s)
                    row.checked_at = now
                    if row.next_run_at is not None and row.next_run_at <= now:
                        due = row.next_run_at
                        self.dispatch(
                            s, actor, row, "schedule:" + due.isoformat(), due, spec.trigger.kind
                        )
                        if spec.trigger.kind == "interval":
                            seconds = spec.trigger.interval_seconds
                            assert seconds is not None
                            row.next_run_at = due + timedelta(
                                seconds=((now - due).total_seconds() // seconds + 1) * seconds
                            )
                        else:
                            row.next_run_at = next_instant(spec.trigger, now)
                        dispatched += 1
                    elif spec.trigger.kind == "action.committed":
                        source = self.resource(s, actor, spec.trigger.ontology_resource_id)  # type: ignore[arg-type]
                        events = list(
                            s.scalars(
                                select(OutboxEvent)
                                .where(
                                    OutboxEvent.tenant_id == tenant,
                                    OutboxEvent.ontology_id == source.ontology_id,
                                    OutboxEvent.category == "action.committed",
                                    OutboxEvent.created_at >= row.event_time,
                                    ~exists(
                                        select(AutomationReceipt.id).where(
                                            AutomationReceipt.tenant_id == tenant,
                                            AutomationReceipt.automation_id == key,
                                            AutomationReceipt.dedup_key
                                            == "event:" + OutboxEvent.id.cast(Text),
                                        )
                                    ),
                                )
                                .order_by(OutboxEvent.created_at, OutboxEvent.id)
                                .limit(GSettings().dispatch_batch - dispatched)
                            )
                        )
                        for event in events:
                            self.dispatch(
                                s,
                                actor,
                                row,
                                "event:" + str(event.id),
                                event.created_at,
                                "action.committed",
                            )
                            dispatched += 1
                    row.last_error = None
            except ApplicationError as exc:
                # Revocation records a fixed failure and disables further dispatch.
                # No execution borrows controller authority.
                with self.sessions.begin() as s:
                    failed_row = s.get(AutomationState, (tenant, key), with_for_update=True)
                    if failed_row and failed_row.enabled and failed_row.activation_id == activation:
                        failed_row.checked_at = clock(s)
                        failed_row.last_error = (
                            "capacity" if exc.status_code == 503 else "authorization_or_contract"
                        )
                        if exc.status_code != 503:
                            failed_row.enabled, failed_row.next_run_at = False, None
                        self.audit(s, actor, "automation_dispatch_denied", key)
        return dispatched
