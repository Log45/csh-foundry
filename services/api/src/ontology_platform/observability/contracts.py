from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from ontology_platform.pipelines.contracts import ExecutionJobView
from ontology_platform.projects.contracts import Model


class LineageNode(Model):
    key: str
    kind: str
    resource_id: UUID
    version_id: UUID | None = None
    local_id: str | None = None
    ontology_id: str | None = None
    schema_version: str | None = None


class DependencyEdge(Model):
    id: str
    source: LineageNode
    target: LineageNode
    relation: str
    mode: Literal["DESIGN", "EXECUTION"]
    certainty: Literal["EXACT_VERSION", "RESOURCE", "POTENTIAL", "HISTORICAL"]
    provenance: str


class Traversal(Model):
    root: LineageNode
    direction: Literal["upstream", "downstream"] = "upstream"
    depth: int = Field(default=3, ge=1, le=8)
    max_nodes: int = Field(default=100, ge=1, le=200)
    max_edges: int = Field(default=200, ge=1, le=400)


class IndexStatus(Model):
    complete: bool
    generation: int
    indexed_generation: int
    cursor: str


class LineageGraph(Model):
    format_version: Literal[1] = 1
    nodes: list[LineageNode]
    edges: list[DependencyEdge]
    truncated: bool
    indexing: IndexStatus


class ImpactPath(Model):
    target: LineageNode
    edges: list[DependencyEdge]
    certainty: str
    reason: str


class ImpactResult(Model):
    graph: LineageGraph
    paths: list[ImpactPath]


class FreshnessInput(Model):
    enabled: bool = True
    expected_interval_seconds: int | None = Field(default=None, ge=60, le=31536000)
    max_age_seconds: int | None = Field(default=None, ge=60, le=31536000)


class FreshnessStatus(Model):
    resource_id: UUID
    state: Literal["FRESH", "STALE", "UNKNOWN", "DISABLED"]
    reason: str
    policy: FreshnessInput | None
    checked_at: datetime
    last_committed_at: datetime | None
    last_version_id: UUID | None
    age_seconds: float | None
    last_successful_run_id: UUID | None = None
    last_failed_run_id: UUID | None = None


class FreshnessDependencies(Model):
    statuses: list[FreshnessStatus]
    indexing_complete: bool
    truncated: bool


class EventView(Model):
    id: UUID
    resource_id: UUID
    execution_id: UUID
    event_type: str
    severity: str
    state: str
    attempt: int
    created_at: datetime


class NodeTimeline(Model):
    node_id: str
    state: str
    attempt: int
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: float | None
    error_category: str | None
    measured_metrics: dict[str, float]


class ExecutionObservation(Model):
    execution: ExecutionJobView
    node_timeline: list[NodeTimeline] = Field(default_factory=list)
    duration_seconds: float | None
    queue_delay_seconds: float | None
    metric_status: Literal["MEASURED", "UNAVAILABLE"]
    error_category: str | None


class HealthSummary(Model):
    resource_id: UUID
    executions: list[ExecutionObservation]
    consecutive_failures: int
    history_truncated: bool
    last_success_id: UUID | None
    last_failure_id: UUID | None
    active_ids: list[UUID]


class Dashboard(Model):
    checked_at: datetime
    days: int
    execution_counts: dict[str, int]
    recent_failures: list[ExecutionObservation]
    sampled_resources: int
    truncated: bool


class ColumnDependency(Model):
    output: str
    input_name: str
    input_column: str
    kind: Literal["VALUE", "ROW", "ORDER"]


class ColumnLineage(Model):
    status: Literal["EXACT", "PARTIAL", "UNSUPPORTED"]
    reason: str
    records: list[ColumnDependency]
    inputs: dict[str, LineageNode]
    truncated: bool = False
