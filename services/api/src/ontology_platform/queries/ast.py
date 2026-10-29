"""Bounded, storage-independent Phase 2 query contracts."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

MAX_DEPTH = 8
MAX_PREDICATES = 64
MAX_NODES = 128
MAX_PAGE = 200
MAX_SORT = 4
MAX_SELECT = 32
MAX_TRAVERSAL = 4
MAX_METRICS = 8
MAX_GROUPS = 100


class QueryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


Name = Annotated[str, Field(strict=True, min_length=1, max_length=200)]


class Predicate(QueryModel):
    property: Name
    operator: Literal[
        "eq",
        "ne",
        "gt",
        "gte",
        "lt",
        "lte",
        "is_null",
        "is_not_null",
        "contains",
        "starts_with",
        "ends_with",
    ]
    value: JsonValue = None

    @model_validator(mode="after")
    def operand(self) -> Self:
        if (
            len(
                json.dumps(
                    self.value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
                ).encode()
            )
            > 8192
        ):
            raise ValueError("Query operand exceeds 8192 bytes")
        null_operator = self.operator in {"is_null", "is_not_null"}
        if null_operator and self.value is not None:
            raise ValueError("Null operators do not accept operands")
        if not null_operator and ("value" not in self.model_fields_set or self.value is None):
            raise ValueError("Comparisons require a nonnull operand; use a null operator")
        return self


class All(QueryModel):
    conditions: tuple[Filter, ...] = Field(alias="and", min_length=1, max_length=64)


class AnyOf(QueryModel):
    conditions: tuple[Filter, ...] = Field(alias="or", min_length=1, max_length=64)


class Negation(QueryModel):
    condition: Filter = Field(alias="not")


Filter = Predicate | All | AnyOf | Negation
All.model_rebuild()
AnyOf.model_rebuild()
Negation.model_rebuild()


def complexity(*filters: Filter | None) -> None:
    nodes = predicates = 0
    pending = [(f, 1) for f in filters if f is not None]
    while pending:
        node, depth = pending.pop()
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            raise ValueError("Query Boolean complexity limit exceeded")
        if isinstance(node, Predicate):
            predicates += 1
        elif isinstance(node, Negation):
            pending.append((node.condition, depth + 1))
        else:
            pending.extend((child, depth + 1) for child in node.conditions)
    if predicates > MAX_PREDICATES:
        raise ValueError("Too many query predicates")


class TraversalStep(QueryModel):
    link: Name
    direction: Literal["forward", "inverse"] = "forward"
    filter: Filter | None = None


class Sort(QueryModel):
    property: Name
    direction: Literal["asc", "desc"] = "asc"


class ObjectSetRequest(QueryModel):
    object_type: Name
    filter: Filter | None = None
    traverse: tuple[TraversalStep, ...] = Field(default=(), max_length=MAX_TRAVERSAL)
    result_filter: Filter | None = None

    @model_validator(mode="before")
    @classmethod
    def preflight(cls, data: Any) -> Any:
        # Check raw nesting before recursive union validation to bound hostile input cost.
        if isinstance(data, dict):
            stack = [(data.get(key), 1) for key in ("filter", "result_filter")]
            steps = data.get("traverse", ())
            if isinstance(steps, (list, tuple)):
                if len(steps) > MAX_TRAVERSAL:
                    raise ValueError("Too many traversal steps")
                stack.extend((step.get("filter"), 1) for step in steps if isinstance(step, dict))
            count = 0
            while stack:
                node, depth = stack.pop()
                if not isinstance(node, dict):
                    continue
                count += 1
                if depth > MAX_DEPTH or count > MAX_NODES:
                    raise ValueError("Query Boolean complexity limit exceeded")
                for key in ("and", "or"):
                    if isinstance(node.get(key), (list, tuple)):
                        if len(node[key]) > MAX_PREDICATES:
                            raise ValueError("Too many Boolean children")
                        stack.extend((child, depth + 1) for child in node[key])
                if "not" in node:
                    stack.append((node["not"], depth + 1))
        return data

    @model_validator(mode="after")
    def bounds(self) -> Self:
        complexity(self.filter, self.result_filter, *(step.filter for step in self.traverse))
        return self


class QueryRequest(ObjectSetRequest):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "object_type": "Machine",
                    "filter": {
                        "and": [
                            {"property": "operationalStatus", "operator": "eq", "value": "RUNNING"},
                            {"property": "temperatureCelsius", "operator": "gt", "value": "80"},
                        ]
                    },
                    "order_by": [{"property": "temperatureCelsius", "direction": "desc"}],
                    "select": ["machineId", "machineName"],
                    "limit": 50,
                }
            ]
        }
    )
    pagination: Literal["cursor", "offset"] = "cursor"
    order_by: tuple[Sort, ...] = Field(default=(), max_length=MAX_SORT)
    select: tuple[Name, ...] | None = Field(default=None, max_length=MAX_SELECT)
    limit: int = Field(default=50, strict=True, ge=1, le=MAX_PAGE)
    offset: int = Field(default=0, strict=True, ge=0, le=10_000)
    cursor: str | None = Field(default=None, min_length=1, max_length=16_384)

    @model_validator(mode="after")
    def page_contract(self) -> Self:
        if self.cursor and self.pagination == "offset":
            raise ValueError("Offset pagination does not accept cursors")
        if self.cursor and self.offset:
            raise ValueError("Cursor and offset cannot be combined")
        if len({s.property for s in self.order_by}) != len(self.order_by):
            raise ValueError("Duplicate sort properties")
        if self.select is not None and len(set(self.select)) != len(self.select):
            raise ValueError("Duplicate projected properties")
        return self


class Metric(QueryModel):
    name: Name
    operator: Literal["count", "sum", "avg", "min", "max"]
    property: Name | None = None

    @model_validator(mode="after")
    def required_property(self) -> Self:
        if self.operator != "count" and self.property is None:
            raise ValueError("This aggregate requires a property")
        return self


class AggregateRequest(ObjectSetRequest):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "object_type": "Machine",
                    "group_by": "operationalStatus",
                    "metrics": [{"name": "machines", "operator": "count"}],
                }
            ]
        }
    )
    metrics: tuple[Metric, ...] = Field(min_length=1, max_length=MAX_METRICS)
    group_by: Name | None = None
    max_groups: int = Field(default=MAX_GROUPS, strict=True, ge=1, le=MAX_GROUPS)

    @model_validator(mode="after")
    def unique_names(self) -> Self:
        if len({m.name for m in self.metrics}) != len(self.metrics):
            raise ValueError("Duplicate metric names")
        return self


class QueryObject(QueryModel):
    tenant_id: UUID
    ontology_id: str
    object_type_id: str
    object_id: str
    schema_version: str
    version: int
    created_at: datetime
    updated_at: datetime
    properties: dict[str, JsonValue]


class QueryPage(QueryModel):
    object_type: str
    schema_version: str
    items: list[QueryObject]
    next_cursor: str | None
    has_more: bool


class AggregateValue(QueryModel):
    data_type: str
    value: int | float | str | bool | None


class AggregateGroup(QueryModel):
    key: AggregateValue | None
    values: dict[str, AggregateValue]


class AggregateResult(QueryModel):
    object_type: str
    schema_version: str
    groups: list[AggregateGroup]
