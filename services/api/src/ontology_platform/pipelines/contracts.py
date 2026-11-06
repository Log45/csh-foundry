"""Engine-neutral, closed declarative grammar. No source code or opaque executable plans."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, Field, FiniteFloat, JsonValue, model_validator

from ontology_platform.projects.contracts import Model, Name


def valid_column(value: str) -> str:
    if not value.strip() or any(ord(char) < 32 for char in value):
        raise ValueError("Invalid column name")
    return value


Column = Annotated[str, Field(min_length=1, max_length=200), AfterValidator(valid_column)]


class Expression(Model):
    op: Literal[
        "column",
        "literal",
        "add",
        "subtract",
        "multiply",
        "divide",
        "eq",
        "ne",
        "lt",
        "le",
        "gt",
        "ge",
        "and",
        "or",
        "not",
        "is_null",
        "coalesce",
    ]
    column: Column | None = None
    value: str | int | FiniteFloat | bool | None = None
    args: list["Expression"] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def arity(self) -> "Expression":
        expected = (
            0 if self.op in {"column", "literal"} else 1 if self.op in {"not", "is_null"} else 2
        )
        if len(self.args) != expected or (self.op == "column") != (self.column is not None):
            raise ValueError("Invalid expression shape")
        if self.op != "literal" and self.value is not None:
            raise ValueError("Only literals accept values")
        return self


class Aggregate(Model):
    column: Column
    function: Literal["sum", "mean", "min", "max", "count"]
    alias: Column


class Step(Model):
    op: Literal[
        "select",
        "rename",
        "drop",
        "filter",
        "sort",
        "cast",
        "derive",
        "fill_null",
        "deduplicate",
        "aggregate",
        "join",
        "union",
    ]
    columns: list[Column] = Field(default_factory=list, max_length=256)
    mapping: dict[Column, Column] = Field(default_factory=dict, max_length=256)
    expression: Expression | None = None
    name: Column | None = None
    value: str | int | FiniteFloat | bool | None = None
    aggregates: list[Aggregate] = Field(default_factory=list, max_length=256)
    input: Name | None = None
    how: Literal["inner", "left", "full", "semi", "anti"] = "inner"
    descending: bool = False

    @model_validator(mode="after")
    def required(self) -> "Step":
        allowed = {
            "select": {"columns"},
            "drop": {"columns"},
            "rename": {"mapping"},
            "filter": {"expression"},
            "sort": {"columns", "descending"},
            "cast": {"mapping"},
            "derive": {"name", "expression"},
            "fill_null": {"name", "value"},
            "deduplicate": {"columns"},
            "aggregate": {"columns", "aggregates"},
            "join": {"input", "columns", "how"},
            "union": {"input"},
        }
        irrelevant = self.model_fields_set - allowed[self.op] - {"op"}
        if any(
            getattr(self, field)
            != type(self).model_fields[field].get_default(call_default_factory=True)
            for field in irrelevant
        ):
            raise ValueError("Fields do not apply to this operation")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("Duplicate column references")
        if self.op in {"filter", "derive"} and self.expression is None:
            raise ValueError("Expression required")
        if self.op in {"derive", "fill_null"} and self.name is None:
            raise ValueError("Output column required")
        if self.op in {"join", "union"} and self.input is None:
            raise ValueError("Input required")
        if self.op in {"select", "drop", "sort", "join"} and not self.columns:
            raise ValueError("Columns required")
        if self.op in {"cast", "rename"} and not self.mapping:
            raise ValueError("Column mapping required")
        if self.op == "aggregate" and not self.aggregates:
            raise ValueError("Aggregates required")
        return self


class InputContract(Model):
    name: Name
    columns: dict[Column, str] = Field(default_factory=dict, max_length=256)


class Definition(Model):
    engine: Literal["polars"] = "polars"
    inputs: list[InputContract] = Field(min_length=1, max_length=16)
    steps: list[Step] = Field(default_factory=list, max_length=100)
    output_columns: dict[Column, str] = Field(default_factory=dict, max_length=256)

    @model_validator(mode="after")
    def unique(self) -> "Definition":
        if len({i.name for i in self.inputs}) != len(self.inputs):
            raise ValueError("Input names must be unique")
        known = {i.name for i in self.inputs}
        if any(s.input is not None and s.input not in known for s in self.steps):
            raise ValueError("Unknown input")

        # Bound expression complexity independently from serialized HTTP size.
        def depth(e: Expression, level: int = 0) -> None:
            if level > 16:
                raise ValueError("Expression nesting exceeds sixteen levels")
            for arg in e.args:
                depth(arg, level + 1)

        for step in self.steps:
            if step.expression:
                depth(step.expression)
        return self


NodeId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")]


class DAGInput(InputContract):
    name: NodeId
    dataset_id: UUID
    version_id: UUID


class DAGNode(Model):
    id: NodeId
    inputs: dict[Literal["input", "right"], NodeId] = Field(min_length=1, max_length=2)
    config: Step

    @model_validator(mode="after")
    def ports(self) -> "DAGNode":
        binary = self.config.op in {"join", "union"}
        if set(self.inputs) != ({"input", "right"} if binary else {"input"}):
            raise ValueError("Operation input ports do not match arity")
        if binary and self.config.input != "right":
            raise ValueError("DAG binary configuration input must be right")
        # Reuse canonical expression depth/closed operation validation.
        Definition(inputs=[InputContract(name="right")], steps=[self.config])
        return self


class DAGOutput(Model):
    id: NodeId
    source: NodeId
    format: Literal["parquet", "csv", "ndjson"] = "parquet"
    columns: dict[Column, str] = Field(default_factory=dict, max_length=256)
    dataset_id: UUID | None = None
    project_id: UUID | None = None
    name: Name | None = None

    @model_validator(mode="after")
    def target(self) -> "DAGOutput":
        if self.dataset_id is not None:
            if self.project_id is not None or self.name is not None:
                raise ValueError("Existing targets cannot specify resource creation")
        elif self.project_id is None or self.name is None:
            raise ValueError("New output requires Project and name")
        return self


class DAGDefinition(Model):
    format_version: Literal[2]
    engine: Literal["polars"] = "polars"
    inputs: list[DAGInput] = Field(min_length=1, max_length=16)
    nodes: list[DAGNode] = Field(max_length=100)
    outputs: list[DAGOutput] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def graph(self) -> "DAGDefinition":
        if len(self.model_dump_json().encode()) > 262144:
            raise ValueError("DAG exceeds 256 KiB")
        from ontology_platform.pipelines.dag import topology

        topology(self)
        return self


class DefinitionView(Model):
    id: UUID
    pipeline_id: UUID
    sequence: int
    specification: Definition | DAGDefinition
    created_by: str
    created_at: datetime


class InputVersion(Model):
    name: Name
    dataset_id: UUID
    version_id: UUID


class StartRun(Model):
    definition_id: UUID
    inputs: list[InputVersion] = Field(min_length=1, max_length=16)
    output_dataset_id: UUID | None = None
    parameters: dict[str, JsonValue] = Field(default_factory=dict, max_length=0)


class NodeExecutionView(Model):
    node_id: str
    state: str
    attempt: int
    error: str | None = None


class OutputPublicationView(Model):
    output_id: str
    dataset_id: UUID
    version_id: UUID
    state: str


class ExecutionJobView(Model):
    id: UUID
    resource_id: UUID
    kind: str
    state: str
    attempts: int
    error: str | None
    metrics: dict[str, JsonValue]
    output_version_id: UUID | None
    output_dataset_id: UUID | None
    created_at: datetime
    admitted_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    plan_digest: str | None = None
    publication_state: str | None = None
    prepared_output_count: int = 0
    nodes: list[NodeExecutionView] = Field(default_factory=list)
    outputs: list[OutputPublicationView] = Field(default_factory=list)
