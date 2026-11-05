from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from ontology_platform.functions.contracts import DefinitionIdentityView
from ontology_platform.projects.contracts import Model, Name


class Trigger(Model):
    kind: Literal["manual", "interval", "daily", "action.committed"]
    interval_seconds: int | None = Field(default=None, ge=60, le=365 * 86400)
    hour: int | None = Field(default=None, ge=0, le=23)
    minute: int | None = Field(default=None, ge=0, le=59)
    timezone: Literal["UTC"] = "UTC"
    ontology_resource_id: UUID | None = None

    @model_validator(mode="after")
    def shape(self) -> "Trigger":
        required = {
            "manual": set(),
            "interval": {"interval_seconds"},
            "daily": {"hour", "minute"},
            "action.committed": {"ontology_resource_id"},
        }[self.kind]
        present = {
            k
            for k in ("interval_seconds", "hour", "minute", "ontology_resource_id")
            if getattr(self, k) is not None
        }
        if present != required:
            raise ValueError("Trigger fields do not match kind")
        return self


class AutomationDefinition(Model):
    trigger: Trigger
    function_id: UUID
    function_definition_id: UUID
    inputs: dict[str, JsonValue] = Field(max_length=32)
    missed_run_policy: Literal["coalesce"] = "coalesce"
    retry_policy: Literal["bounded-idempotent"] = "bounded-idempotent"


class Enable(Model):
    definition_id: UUID
    enabled: bool


class Manual(Model):
    idempotency_key: Name


class ScheduleView(Model):
    automation_id: UUID
    definition_id: UUID
    enabled: bool
    next_run_at: datetime | None
    owner: str
    last_error: str | None


class ReceiptView(Model):
    automation_id: UUID
    definition_id: UUID
    id: UUID
    trigger_kind: str
    trigger_at: datetime
    job_id: UUID | None
    error: str | None
    created_at: datetime


class AutomationDefinitionView(DefinitionIdentityView):
    specification: AutomationDefinition
