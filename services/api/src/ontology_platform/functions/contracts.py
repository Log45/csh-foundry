"""Closed versioned contracts; deliberately no executable code or recursive schemas."""

import json
import math
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ontology_platform.projects.contracts import Model, Name


class GSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FOUNDRY_G_", extra="ignore")
    media_bytes: int = Field(default=256 * 1024**2, ge=1, le=1024**3)
    media_items: int = Field(default=1000, ge=1, le=10000)
    tenant_media_bytes: int = Field(default=10 * 1024**3, ge=1)
    project_media_bytes: int = Field(default=5 * 1024**3, ge=1)
    pixels: int = Field(default=20_000_000, ge=1)
    preview_bytes: int = Field(default=1024**2, ge=1)
    parse_seconds: int = Field(default=30, ge=1, le=120)
    input_bytes: int = Field(default=16384, ge=1, le=32768)
    output_bytes: int = Field(default=16384, ge=1, le=32768)
    function_jobs: int = Field(default=2, ge=1, le=32)
    project_schedules: int = Field(default=50, ge=1, le=1000)
    schedules: int = Field(default=100, ge=1, le=1000)
    dispatch_batch: int = Field(default=20, ge=1, le=100)
    dispatch_per_minute: int = Field(default=60, ge=1, le=10000)
    backlog: int = Field(default=100, ge=1, le=1000)
    history: int = Field(default=10000, ge=1, le=100000)


Scalar = str | int | float | bool | None


class ValueType(Model):
    type: Literal["string", "integer", "number", "boolean"]
    nullable: bool = False


def typed(values: dict[str, JsonValue], contract: dict[str, ValueType], maximum: int) -> None:
    if (
        len(json.dumps(values, allow_nan=False).encode()) > maximum
        or values.keys() != contract.keys()
    ):
        raise ValueError("Values exceed budget or do not match contract")
    for name, rule in contract.items():
        value = values[name]
        if value is None and rule.nullable:
            continue
        allowed = {"string": (str,), "integer": (int,), "number": (int, float), "boolean": (bool,)}
        if type(value) not in allowed[rule.type]:
            raise ValueError("Value type mismatch")
        if isinstance(value, str) and len(value) > 8192:
            raise ValueError("String exceeds budget")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not math.isfinite(value) or abs(value) > 2**53 - 1:
                raise ValueError("Numeric value outside portable range")


class FunctionLimits(Model):
    wall_seconds: int = Field(default=30, ge=1, le=60)
    cpu_seconds: int = Field(default=10, ge=1, le=30)
    memory_bytes: int = Field(default=256 * 1024**2, ge=128 * 1024**2, le=512 * 1024**2)
    temporary_bytes: int = Field(default=8 * 1024**2, ge=65536, le=16 * 1024**2)


class FunctionDefinition(Model):
    implementation: Literal["identity.v1", "text.normalize.v1", "number.add.v1"]
    input_schema: dict[Name, ValueType] = Field(min_length=1, max_length=32)
    output_schema: dict[Name, ValueType] = Field(min_length=1, max_length=32)
    configuration: dict[str, JsonValue] = Field(default_factory=dict, max_length=0)
    limits: FunctionLimits = Field(default_factory=FunctionLimits)
    required_permissions: Literal["project:write"] = "project:write"
    deterministic: Literal[True] = True
    idempotent: Literal[True] = True
    error_contract: Literal["bounded-v1"] = "bounded-v1"

    @model_validator(mode="after")
    def supported_contract(self) -> "FunctionDefinition":
        if self.implementation == "identity.v1":
            if self.input_schema != self.output_schema:
                raise ValueError("Identity requires identical input and output contracts")
        else:
            inputs = (
                {"text": ValueType(type="string")}
                if self.implementation == "text.normalize.v1"
                else {"left": ValueType(type="number"), "right": ValueType(type="number")}
            )
            outputs = {"result": ValueType(type="string" if "text" in inputs else "number")}
            if self.input_schema != inputs or self.output_schema != outputs:
                raise ValueError("Implementation requires its exact versioned contract")
        return self


class DefinitionIdentityView(Model):
    resource_id: UUID
    id: UUID
    kind: str
    sequence: int
    created_by: str
    created_at: datetime


class GovernedDefinitionView(DefinitionIdentityView):
    specification: dict[str, JsonValue]


class Invoke(Model):
    definition_id: UUID
    inputs: dict[str, JsonValue] = Field(max_length=32)
    idempotency_key: Name


class ResultView(Model):
    job_id: UUID
    definition_id: UUID
    values: dict[str, JsonValue]
    created_at: datetime


class FunctionDefinitionView(DefinitionIdentityView):
    specification: FunctionDefinition
