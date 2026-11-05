"""Function adapter for the existing leased worker; no privileged handles enter the child."""

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ontology_platform.automations.contracts import AutomationDefinition
from ontology_platform.automations.service import AutomationService
from ontology_platform.db.governance import missing
from ontology_platform.db.models import ExecutionJob, FunctionInvocation, FunctionResult
from ontology_platform.db.session import clock
from ontology_platform.errors import ApplicationError
from ontology_platform.execution.config import ExecutionSettings
from ontology_platform.execution.isolation import isolated
from ontology_platform.functions.contracts import FunctionDefinition, GSettings, typed
from ontology_platform.functions.service import FunctionService
from ontology_platform.security.interfaces import Principal

if TYPE_CHECKING:
    from ontology_platform.execution.worker import ExecutionWorker


def pinned_budget(job: ExecutionJob, name: str, current: int) -> int:
    value = job.request.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 32768:
        raise ApplicationError("invalid_budget", "Invalid pinned function budget", 409)
    return min(value, current)


def authorize(
    svc: FunctionService, s: Session, actor: Principal, job: ExecutionJob
) -> FunctionDefinition:
    svc.artifact(s, actor, job.resource_id, True)
    invocation = s.get(FunctionInvocation, (actor.tenant_id, job.id))
    if invocation is None:
        raise missing("Function invocation")
    definition = svc.governed_definition(s, actor, job.resource_id, invocation.definition_id)
    spec = FunctionDefinition.model_validate(definition.specification)
    if spec.implementation != job.request.get("implementation"):
        raise ApplicationError("implementation_version", "Pinned implementation unavailable", 409)
    automation = job.request.get("automation")
    if isinstance(automation, dict):
        automations = AutomationService(svc.sessions, svc.authorizer, svc.settings, svc.store)
        row = automations.state(s, actor, UUID(str(automation["resource_id"])), True)
        if (
            not row.enabled
            or str(row.activation_id) != automation.get("activation_id")
            or str(row.definition_id) != automation["definition_id"]
            or row.owner != actor.principal_id
        ):
            raise ApplicationError(
                "automation_disabled", "Automation binding no longer active", 409
            )
        bound = automations.governed_definition(s, actor, row.automation_id, row.definition_id)
        target = AutomationDefinition.model_validate(bound.specification)
        if (
            target.function_id != job.resource_id
            or target.function_definition_id != invocation.definition_id
        ):
            raise ApplicationError("invalid_binding", "Automation target mismatch", 409)
        automations.validate_target(s, actor, bound.specification)
    typed(
        invocation.inputs,
        spec.input_schema,
        pinned_budget(job, "input_limit", GSettings().input_bytes),
    )
    return spec


def execute(
    worker: "ExecutionWorker",
    tenant: UUID,
    key: UUID,
    token: UUID,
    actor: Principal,
    limits: ExecutionSettings,
) -> None:
    root = worker.service
    svc = FunctionService(root.sessions, root.authorizer, root.settings, root.store)
    with svc.scope(actor) as s:
        job = worker.fenced(s, tenant, key, token)
        spec = authorize(svc, s, actor, job)
        request = {
            "specification": spec.model_dump(mode="json"),
            "inputs": job.request["inputs"],
            "input_limit": pinned_budget(job, "input_limit", GSettings().input_bytes),
            "output_limit": pinned_budget(job, "output_limit", GSettings().output_bytes),
        }
        definition_id = UUID(str(job.request["definition_id"]))
        job.state, job.started_at = "RUNNING", clock(s)
    with tempfile.TemporaryDirectory(prefix="foundry-function-") as directory:
        result = isolated(
            "function",
            request,
            Path(directory),
            limits,
            lambda: worker.heartbeat(tenant, key, token),
        )
    if "error" in result:
        worker.fail(tenant, key, token, str(result["error"]), False, result.get("metrics", {}))
        return
    with svc.scope(actor) as s:
        job = worker.fenced(s, tenant, key, token)
        authorize(svc, s, actor, job)
        typed(
            result["values"],
            spec.output_schema,
            pinned_budget(job, "output_limit", GSettings().output_bytes),
        )
        s.execute(
            text("SELECT set_config('foundry.execution_token', :token, true)"),
            {"token": str(token)},
        )
        s.add(
            FunctionResult(
                tenant_id=tenant, job_id=key, definition_id=definition_id, values=result["values"]
            )
        )
        s.flush()
        job.state, job.completed_at, job.metrics = "SUCCEEDED", clock(s), result.get("metrics", {})
        job.token, job.lease_until = None, None
        svc.audit(s, actor, "function_succeeded", key)
