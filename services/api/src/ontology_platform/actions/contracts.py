"""Bounded request and redacted action result contracts."""

import json
from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import ConfigDict, Field, JsonValue, model_validator

from ontology_platform.contracts import APIModel


class ActionRequest(APIModel):
    parameters: dict[str, JsonValue] = Field(default_factory=dict, max_length=32)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if len(json.dumps(self.model_dump(mode="json"), ensure_ascii=False).encode()) > 65536:
            raise ValueError("Action request exceeds 64 KiB")
        return self


class ExecuteRequest(ActionRequest):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "idempotency_key": "maintenance-update-001",
                    "parameters": {
                        "machineId": "MCH-001",
                        "newStatus": "STOPPED",
                        "expectedRevision": 1,
                    },
                }
            ]
        }
    )
    idempotency_key: str = Field(min_length=1, max_length=128)


class Change(APIModel):
    operation: str
    object_type: str
    object_id: str
    previous_revision: int | None = None
    new_revision: int | None = None
    properties: list[str] = Field(default_factory=list)
    link: str | None = None
    target_type: str | None = None
    target_id: str | None = None


class ActionResult(APIModel):
    execution_id: UUID | None = None
    action_id: str
    action_version: str
    schema_version: str
    changes: list[Change]
    advisory: bool = False


class ExecutionView(APIModel):
    id: UUID
    action_id: str
    action_version: str
    schema_version: str
    principal_id: str
    status: str
    created_at: datetime
    result: ActionResult


class HistoryPage(APIModel):
    items: list[ExecutionView]
    has_more: bool
