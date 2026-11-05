"""Typed pure functions, immutable publication and shared execution admission."""

import hashlib
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ontology_platform.branching.service import page
from ontology_platform.db.governance import missing
from ontology_platform.db.models import (
    ExecutionJob,
    FunctionInvocation,
    FunctionResult,
    GovernedDefinition,
)
from ontology_platform.errors import ApplicationError
from ontology_platform.execution.config import ExecutionSettings
from ontology_platform.functions.contracts import (
    FunctionDefinition,
    GovernedDefinitionView,
    GSettings,
    Invoke,
    ResultView,
    typed,
)
from ontology_platform.pipelines.contracts import ExecutionJobView
from ontology_platform.pipelines.service import PipelineService
from ontology_platform.projects.service import conflict
from ontology_platform.security.interfaces import Principal


class FunctionService(PipelineService):
    resource_kind = "FUNCTION"

    def governed_definition(
        self, s: Session, p: Principal, key: UUID, version: UUID
    ) -> GovernedDefinition:
        self.artifact(s, p, key)
        row = s.get(GovernedDefinition, (p.tenant_id, key, version))
        if row is None or row.kind != self.resource_kind:
            raise missing("Published definition")
        return row

    def publish_spec(
        self, s: Session, p: Principal, key: UUID, spec: dict[str, Any]
    ) -> GovernedDefinitionView:
        self.artifact(s, p, key, True)
        count = (
            s.scalar(
                select(func.count())
                .select_from(GovernedDefinition)
                .where(
                    GovernedDefinition.tenant_id == p.tenant_id,
                    GovernedDefinition.resource_id == key,
                )
            )
            or 0
        )
        if count >= GSettings().history:
            raise conflict("Retained definition limit reached")
        row = GovernedDefinition(
            tenant_id=p.tenant_id,
            resource_id=key,
            id=uuid4(),
            kind=self.resource_kind,
            sequence=count + 1,
            specification=spec,
            created_by=p.principal_id,
            target_resource_id=UUID(spec["function_id"])
            if self.resource_kind == "AUTOMATION"
            else None,
            target_definition_id=UUID(spec["function_definition_id"])
            if self.resource_kind == "AUTOMATION"
            else None,
            event_resource_id=(
                UUID(spec["trigger"]["ontology_resource_id"])
                if self.resource_kind == "AUTOMATION"
                and spec["trigger"].get("ontology_resource_id")
                else None
            ),
        )
        s.add(row)
        s.flush()
        self.audit(s, p, self.resource_kind.lower() + "_publish", row.id)
        return GovernedDefinitionView.model_validate(row)

    def publish_function(
        self, p: Principal, key: UUID, spec: FunctionDefinition
    ) -> GovernedDefinitionView:
        with self.scope(p) as s:
            return self.publish_spec(s, p, key, spec.model_dump(mode="json"))

    def published_definitions(
        self, p: Principal, key: UUID, limit: int = 50, offset: int = 0
    ) -> list[GovernedDefinitionView]:
        page(limit, offset)
        with self.scope(p) as s:
            self.artifact(s, p, key)
            rows = s.scalars(
                select(GovernedDefinition)
                .where(
                    GovernedDefinition.tenant_id == p.tenant_id,
                    GovernedDefinition.resource_id == key,
                )
                .order_by(GovernedDefinition.sequence.desc())
                .limit(limit)
                .offset(offset)
            )
            result = []
            for row in rows:
                if self.resource_kind == "MEDIA_SET":
                    # Snapshot IDs may contain inaccessible source identities; filter at service.
                    from ontology_platform.media.service import MediaService

                    if isinstance(self, MediaService):
                        row_view = GovernedDefinitionView.model_validate(row)
                        row_view.specification = {
                            "items": [
                                str(i.id) for i in self.snapshot_items(s, p, key, row.id, 10000, 0)
                            ]
                        }
                        result.append(row_view)
                elif self.resource_kind == "AUTOMATION":
                    # Do not disclose the target function or event source through shares alone.
                    from ontology_platform.automations.service import AutomationService

                    if isinstance(self, AutomationService):
                        self.validate_target(s, p, row.specification)
                        result.append(GovernedDefinitionView.model_validate(row))
                else:
                    result.append(GovernedDefinitionView.model_validate(row))
            return result

    def admit(
        self,
        s: Session,
        p: Principal,
        key: UUID,
        body: Invoke,
        automation: dict[str, str] | None = None,
    ) -> ExecutionJob:
        resource = self.artifact(s, p, key, True)
        definition = self.governed_definition(s, p, key, body.definition_id)
        spec = FunctionDefinition.model_validate(definition.specification)
        try:
            typed(body.inputs, spec.input_schema, GSettings().input_bytes)
        except (ValueError, OverflowError) as exc:
            raise ApplicationError(
                "invalid_input", "Function input violates contract", 422
            ) from exc
        digest = hashlib.sha256(body.idempotency_key.encode()).hexdigest()
        previous = s.scalar(
            select(FunctionInvocation).where(
                FunctionInvocation.tenant_id == p.tenant_id,
                FunctionInvocation.function_id == key,
                FunctionInvocation.actor == p.principal_id,
                FunctionInvocation.key == digest,
            )
        )
        if previous:
            if previous.definition_id != body.definition_id or previous.inputs != body.inputs:
                raise conflict("Idempotency key was already used with different inputs")
            job = s.get(ExecutionJob, (p.tenant_id, previous.job_id))
            assert job is not None
            return job
        count = (
            s.scalar(
                select(func.count())
                .select_from(FunctionInvocation)
                .where(
                    FunctionInvocation.tenant_id == p.tenant_id,
                    FunctionInvocation.function_id == key,
                )
            )
            or 0
        )
        if count >= GSettings().history:
            raise conflict("Retained invocation limit reached")
        limits = ExecutionSettings()
        for name in type(spec.limits).model_fields:
            setattr(limits, name, min(getattr(limits, name), getattr(spec.limits, name)))
        self.capacity(s, p, limits)
        request = body.model_dump(mode="json") | {
            "implementation": spec.implementation,
            "input_limit": GSettings().input_bytes,
            "output_limit": GSettings().output_bytes,
        }
        if automation:
            request["automation"] = automation
        job = ExecutionJob(
            tenant_id=p.tenant_id,
            id=uuid4(),
            resource_id=key,
            project_id=resource.project_id,
            kind="FUNCTION",
            request=request,
            principal=p.model_dump(mode="json"),
            limits=limits.model_dump(mode="json"),
        )
        s.add(job)
        s.flush()
        s.add(
            FunctionInvocation(
                tenant_id=p.tenant_id,
                job_id=job.id,
                function_id=key,
                definition_id=body.definition_id,
                key=digest,
                actor=p.principal_id,
                inputs=body.inputs,
            )
        )
        s.flush()
        self.audit(s, p, "function_invoke", job.id)
        return job

    def invoke(self, p: Principal, key: UUID, body: Invoke) -> ExecutionJobView:
        with self.scope(p) as s:
            return self.job_view(s, p, self.admit(s, p, key, body))

    def result(self, p: Principal, key: UUID) -> ResultView:
        with self.scope(p) as s:
            job = self.job(s, p, key)
            # Inputs are scalar-only, no resource identifiers are interpreted as authority.
            self.artifact(s, p, job.resource_id)
            row = s.get(FunctionResult, (p.tenant_id, key))
            if row is None or job.state != "SUCCEEDED":
                raise missing("Successful function result")
            return ResultView.model_validate(row)

    def provenance(self, p: Principal, key: UUID) -> dict[str, Any]:
        with self.scope(p) as s:
            job = self.job(s, p, key)
            self.artifact(s, p, job.resource_id)
            invocation = s.get(FunctionInvocation, (p.tenant_id, key))
            if invocation is None:
                raise missing("Function invocation")
            entry = {
                "job_id": str(key),
                "function_id": str(job.resource_id),
                "definition_id": str(invocation.definition_id),
                "actor": invocation.actor,
                "implementation": job.request["implementation"],
                "state": job.state,
                "attempts": job.attempts,
                "created_at": job.created_at.isoformat(),
            }
            automation = job.request.get("automation")
            if isinstance(automation, dict):
                try:
                    row = self.resource(s, p, UUID(str(automation["resource_id"])))
                except ApplicationError as exc:
                    if exc.status_code not in {403, 404}:
                        raise
                else:
                    entry["automation_id"] = str(row.id)
                    entry["automation_definition_id"] = str(automation["definition_id"])
            return entry
