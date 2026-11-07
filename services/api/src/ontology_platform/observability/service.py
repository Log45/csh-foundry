import hashlib
from collections import Counter, deque
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import exists, or_, select, text
from sqlalchemy.orm import Session

from ontology_platform.db.governance import missing
from ontology_platform.db.models import (
    ApplicationVersion,
    ArtifactVersion,
    DAGNodeExecution,
    DAGPreparedOutput,
    DatasetVersion,
    ExecutionJob,
    FreshnessPolicy,
    GovernedDefinition,
    LineageEdge,
    LineagePending,
    MappingDefinition,
    OperationalEvent,
    PipelineDefinition,
    Project,
    Resource,
)
from ontology_platform.db.session import clock
from ontology_platform.errors import ApplicationError
from ontology_platform.observability.contracts import (
    ColumnLineage,
    Dashboard,
    DependencyEdge,
    EventView,
    ExecutionObservation,
    FreshnessDependencies,
    FreshnessInput,
    FreshnessStatus,
    HealthSummary,
    ImpactPath,
    ImpactResult,
    IndexStatus,
    LineageGraph,
    LineageNode,
    NodeTimeline,
    Traversal,
)
from ontology_platform.observability.index import INDEX_PREFIX, node, ontology_node, reconcile
from ontology_platform.pipelines.service import PipelineService
from ontology_platform.security.interfaces import Principal

SAFE_ERRORS = {
    "storage_unavailable": "STORAGE_UNAVAILABLE",
    "resource_limit": "RESOURCE_BUDGET",
    "invalid_dataset": "INVALID_SCHEMA",
    "invalid_pipeline": "VALIDATION",
    "cancelled": "CANCELLATION",
    "lease_expired": "LEASE_EXPIRED",
    "publication_conflict": "PUBLICATION_CONFLICT",
    "forbidden": "UNAUTHORIZED_DEPENDENCY",
}


class ObservabilityService(PipelineService):
    def index_status(self, s: Session, p: Principal, key: UUID) -> IndexStatus:
        row = s.get(LineagePending, (p.tenant_id, key))
        # A source resource's downstream edges may be owned by another visible origin.
        # Completeness therefore covers the authorized registry scope, never hidden counts.
        lagging = s.scalar(
            select(LineagePending.resource_id)
            .join(
                Resource,
                (LineagePending.tenant_id == Resource.tenant_id)
                & (LineagePending.resource_id == Resource.id),
            )
            .where(
                LineagePending.tenant_id == p.tenant_id,
                self.visible(p),
                Resource.state == "ACTIVE",
                or_(
                    LineagePending.generation != LineagePending.indexed_generation,
                    ~LineagePending.cursor.startswith(INDEX_PREFIX),
                ),
            )
            .limit(1)
        )
        return IndexStatus(
            complete=row is not None
            and row.generation == row.indexed_generation
            and row.cursor.startswith(INDEX_PREFIX)
            and lagging is None
            or row is None
            and s.get(Project, (p.tenant_id, key)) is not None
            and lagging is None,
            generation=row.generation if row else 0,
            indexed_generation=row.indexed_generation if row else 0,
            cursor="",
        )  # internal checkpoint IDs are not public metadata

    def status_index(self, p: Principal, key: UUID) -> IndexStatus:
        with self.scope(p) as s:
            self.resource(s, p, key)
            return self.index_status(s, p, key)

    def backfill(self, p: Principal, key: UUID, batch: int) -> IndexStatus:
        if not 1 <= batch <= 100:
            raise ApplicationError("invalid_limit", "Batch must be between 1 and 100", 422)
        with self.scope(p) as s:
            row = self.resource(s, p, key)
            self.project(s, p, row.project_id, write=True)
            pending = s.get(LineagePending, (p.tenant_id, key), with_for_update=True)
            if pending is not None:
                if pending.generation == pending.indexed_generation and pending.cursor.startswith(
                    INDEX_PREFIX
                ):
                    pending.generation += 1
                    pending.cursor = ""
                reconcile(s, pending, batch)
                self.audit(s, p, "lineage_reconcile", key)
            return self.index_status(s, p, key)

    def visible_node(self, s: Session, p: Principal, value: LineageNode) -> bool:
        try:
            if value.kind == "PROJECT":
                self.project(s, p, value.resource_id)
                return value.key == node("PROJECT", value.resource_id).key
            resource = self.resource(s, p, value.resource_id)
            canonical_type = value.kind in {"ONTOLOGY_OBJECT_TYPE", "ONTOLOGY_LINK_TYPE", "ACTION"}
            if canonical_type:
                if (
                    value.ontology_id is None
                    or value.schema_version is None
                    or value.ontology_id != resource.ontology_id
                    or value.schema_version != resource.schema_version
                    or value.local_id is None
                ):
                    return False
                expected_key = ontology_node(
                    value.kind,
                    value.resource_id,
                    value.ontology_id,
                    value.schema_version,
                    value.local_id,
                ).key
            else:
                expected_key = node(
                    value.kind, value.resource_id, value.version_id, value.local_id
                ).key
            if expected_key != value.key:
                return False
            if value.kind == "DATASET_VERSION":
                dataset = s.get(DatasetVersion, (p.tenant_id, value.resource_id, value.version_id))
                return dataset is not None and dataset.state == "COMMITTED"
            if value.kind == "ARTIFACT_VERSION":
                artifact = s.get(
                    ArtifactVersion, (p.tenant_id, value.resource_id, value.version_id)
                )
                return artifact is not None and artifact.state == "COMMITTED"
            if value.kind == "EXECUTION":
                job = s.get(ExecutionJob, (p.tenant_id, value.version_id))
                return job is not None and job.resource_id == value.resource_id
            if value.kind == "MAPPING_DEFINITION":
                return (
                    s.get(MappingDefinition, (p.tenant_id, value.resource_id, value.version_id))
                    is not None
                )
            if value.kind in {"FUNCTION_DEFINITION", "AUTOMATION"}:
                return (
                    s.get(GovernedDefinition, (p.tenant_id, value.resource_id, value.version_id))
                    is not None
                )
            if value.kind in {"PIPELINE_DEFINITION", "TRANSFORM_NODE"}:
                row = s.get(PipelineDefinition, (p.tenant_id, value.resource_id, value.version_id))
                return row is not None and self.visible_definition(s, p, row)
            if value.kind == "APPLICATION_VERSION":
                from ontology_platform.applications.contracts import Document
                from ontology_platform.applications.service import ApplicationService

                app_row = s.get(
                    ApplicationVersion, (p.tenant_id, value.resource_id, value.version_id)
                )
                if app_row is None:
                    return False
                ApplicationService(self.sessions, self.authorizer).references(
                    s, p, Document.model_validate(app_row.document), active=False
                )
            if value.kind in {"ONTOLOGY_OBJECT_TYPE", "ONTOLOGY_LINK_TYPE"}:
                # Canonical schema permission in resource() plus property/type policy.
                if not resource.ontology_id:
                    return False
                self.authorizer.require(p, "schema:read", f"{p.tenant_id}/{resource.ontology_id}")
            return True
        except ApplicationError as exc:
            if exc.status_code in {403, 404, 409}:
                return False
            raise

    def graph(self, p: Principal, body: Traversal) -> LineageGraph:
        with self.scope(p) as s:
            if not any(
                s.scalar(text("SELECT pg_try_advisory_xact_lock(721021,:slot)"), {"slot": slot})
                for slot in range(4)
            ):
                raise ApplicationError(
                    "lineage_capacity", "Lineage capacity is busy; retry later", 429
                )
            if not self.visible_node(s, p, body.root):
                raise missing("Resource")
            nodes = {body.root.key: body.root}
            edges: dict[str, DependencyEdge] = {}
            queue = deque([(body.root.key, 0)])
            visited = {body.root.key}
            truncated = False
            if body.root.kind == "PROJECT" and body.direction == "downstream":
                capacity = min(body.max_nodes - 1, body.max_edges)
                resources = s.scalars(
                    select(Resource)
                    .where(
                        Resource.tenant_id == p.tenant_id,
                        Resource.project_id == body.root.resource_id,
                        Resource.state == "ACTIVE",
                        self.visible(p),
                    )
                    .order_by(Resource.id)
                    .limit(capacity + 1)
                ).all()
                for resource in resources[:capacity]:
                    target = node("RESOURCE", resource.id)
                    if not self.visible_node(s, p, target):
                        continue
                    ident = hashlib.sha256(
                        f"project:{p.tenant_id}:{body.root.resource_id}:{resource.id}".encode()
                    ).hexdigest()
                    nodes[target.key] = target
                    edges[ident] = DependencyEdge(
                        id=ident,
                        source=body.root,
                        target=target,
                        relation="CONTAINS",
                        mode="DESIGN",
                        certainty="RESOURCE",
                        provenance="platform_resources.project_id",
                    )
                    visited.add(target.key)
                    queue.append((target.key, 1))
                truncated = len(resources) > capacity
            complete = self.index_status(s, p, body.root.resource_id).complete
            checks: dict[tuple[str, UUID], bool] = {}
            # A separate examined-edge budget bounds work even for a restricted principal.
            budget = 2000
            while queue and budget > 0:
                key, level = queue.popleft()
                if level >= body.depth:
                    continue
                column = (
                    LineageEdge.target_key
                    if body.direction == "upstream"
                    else LineageEdge.source_key
                )
                rows = s.scalars(
                    select(LineageEdge)
                    .where(
                        LineageEdge.tenant_id == p.tenant_id,
                        column == key,
                        LineageEdge.source_resource_id.in_(
                            select(Resource.id).where(
                                Resource.tenant_id == p.tenant_id,
                                self.visible(p),
                                Resource.state == "ACTIVE",
                            )
                        ),
                        LineageEdge.target_resource_id.in_(
                            select(Resource.id).where(
                                Resource.tenant_id == p.tenant_id,
                                self.visible(p),
                                Resource.state == "ACTIVE",
                            )
                        ),
                        LineageEdge.origin_id.in_(
                            select(Resource.id).where(
                                Resource.tenant_id == p.tenant_id,
                                self.visible(p),
                                Resource.state == "ACTIVE",
                            )
                        ),
                    )
                    .order_by(LineageEdge.id)
                    .limit(min(budget, 500))
                ).all()
                for row in rows:
                    budget -= 1
                    a, b = (
                        LineageNode.model_validate(row.source),
                        LineageNode.model_validate(row.target),
                    )
                    origin = node("RESOURCE", row.origin_id)
                    visible = True
                    for value in [a, b, origin]:
                        scope_key = (value.key, value.resource_id)
                        if scope_key not in checks:
                            checks[scope_key] = self.visible_node(s, p, value)
                        visible = visible and checks[scope_key]
                    if not visible:
                        continue
                    other = a if body.direction == "upstream" else b
                    if (other.key not in nodes and len(nodes) >= body.max_nodes) or len(
                        edges
                    ) >= body.max_edges:
                        truncated = True
                        continue
                    nodes[other.key] = other
                    edges[row.id] = DependencyEdge(
                        id=row.id,
                        source=a,
                        target=b,
                        relation=row.relation,
                        mode=row.mode,
                        certainty=row.certainty,
                        provenance=row.provenance,
                    )
                    if other.key not in visited:
                        visited.add(other.key)
                        queue.append((other.key, level + 1))
            # No scanned/hidden counts or hidden identifiers are exposed.
            status = self.index_status(s, p, body.root.resource_id)
            status.complete = complete and budget > 0
            return LineageGraph(
                nodes=sorted(nodes.values(), key=lambda n: n.key),
                edges=sorted(edges.values(), key=lambda e: e.id),
                truncated=truncated,
                indexing=status,
            )

    def impact(self, p: Principal, body: Traversal) -> ImpactResult:
        graph = self.graph(p, body.model_copy(update={"direction": "downstream"}))
        paths: list[ImpactPath] = []
        pending: deque[tuple[str, list[DependencyEdge]]] = deque([(body.root.key, [])])
        seen = {body.root.key}
        while pending and len(paths) < 100:
            key, trail = pending.popleft()
            for edge in graph.edges:
                if edge.source.key != key or edge.target.key in seen:
                    continue
                seen.add(edge.target.key)
                next_trail = trail + [edge]
                certainty = (
                    "POTENTIAL"
                    if any(e.certainty == "POTENTIAL" for e in next_trail)
                    else edge.certainty
                )
                paths.append(
                    ImpactPath(
                        target=edge.target,
                        edges=next_trail,
                        certainty=certainty,
                        reason="Historical consumption does not imply impact from a future change"
                        if certainty == "HISTORICAL"
                        else "Published dependency; validate compatibility before a change",
                    )
                )
                pending.append((edge.target.key, next_trail))
        return ImpactResult(graph=graph, paths=paths)

    def policy(self, p: Principal, key: UUID, body: FreshnessInput) -> FreshnessStatus:
        with self.scope(p) as s:
            resource = self.resource(s, p, key)
            if resource.resource_type != "DATASET":
                raise missing("Dataset")
            self.project(s, p, resource.project_id, write=True)
            row = s.get(FreshnessPolicy, (p.tenant_id, key))
            if row is None:
                row = FreshnessPolicy(tenant_id=p.tenant_id, resource_id=key)
                s.add(row)
            for name, value in body.model_dump().items():
                setattr(row, name, value)
            row.updated_at = clock(s)
            self.audit(s, p, "freshness_policy", key)
            s.flush()
            return self.freshness_in(s, p, key)

    def freshness_in(self, s: Session, p: Principal, key: UUID) -> FreshnessStatus:
        resource = self.resource(s, p, key)
        if resource.resource_type != "DATASET":
            raise missing("Dataset")
        policy = s.get(FreshnessPolicy, (p.tenant_id, key))
        version = s.scalar(
            select(DatasetVersion)
            .where(
                DatasetVersion.tenant_id == p.tenant_id,
                DatasetVersion.artifact_id == key,
                DatasetVersion.state == "COMMITTED",
            )
            .order_by(DatasetVersion.finalized_at.desc(), DatasetVersion.id)
            .limit(1)
        )
        now = clock(s)
        age = (
            max(0.0, (now - version.finalized_at).total_seconds())
            if version and version.finalized_at
            else None
        )
        threshold = (policy.max_age_seconds or policy.expected_interval_seconds) if policy else None
        state = (
            "DISABLED"
            if policy is None or not policy.enabled
            else "UNKNOWN"
            if age is None or threshold is None
            else "STALE"
            if age > threshold
            else "FRESH"
        )
        producers = s.scalars(
            select(ExecutionJob)
            .join(
                Resource,
                (ExecutionJob.tenant_id == Resource.tenant_id)
                & (ExecutionJob.resource_id == Resource.id),
            )
            .where(
                ExecutionJob.tenant_id == p.tenant_id,
                self.visible(p),
                ExecutionJob.state.in_(["SUCCEEDED", "FAILED"]),
                or_(
                    ExecutionJob.output_dataset_id == key,
                    exists(
                        select(DAGPreparedOutput.job_id).where(
                            DAGPreparedOutput.tenant_id == p.tenant_id,
                            DAGPreparedOutput.job_id == ExecutionJob.id,
                            DAGPreparedOutput.dataset_id == key,
                        )
                    ),
                ),
            )
            .order_by(ExecutionJob.completed_at.desc(), ExecutionJob.id)
            .limit(20)
        ).all()
        visible_producers = []
        for producer in producers:
            try:
                self.resource(s, p, producer.resource_id)
                visible_producers.append(producer)
            except ApplicationError as exc:
                if exc.status_code not in {403, 404}:
                    raise
        return FreshnessStatus(
            resource_id=key,
            state=state,
            reason={
                "DISABLED": "No enabled freshness policy",
                "UNKNOWN": "No committed version or age threshold",
                "STALE": "Last committed version exceeds policy age",
                "FRESH": "Committed version meets policy",
            }[state],
            policy=FreshnessInput.model_validate(policy) if policy else None,
            checked_at=now,
            last_committed_at=version.finalized_at if version else None,
            last_version_id=version.id if version else None,
            age_seconds=age,
            last_successful_run_id=next(
                (r.id for r in visible_producers if r.state == "SUCCEEDED"), None
            ),
            last_failed_run_id=next((r.id for r in visible_producers if r.state == "FAILED"), None),
        )

    def freshness(self, p: Principal, key: UUID) -> FreshnessStatus:
        with self.scope(p) as s:
            return self.freshness_in(s, p, key)

    def freshness_dependencies(self, p: Principal, key: UUID) -> FreshnessDependencies:
        status = self.freshness(p, key)
        if status.last_version_id is None:
            return FreshnessDependencies(statuses=[], indexing_complete=False, truncated=False)
        graph = self.graph(
            p, Traversal(root=node("DATASET_VERSION", key, status.last_version_id), depth=8)
        )
        source_ids = sorted(
            {
                n.resource_id
                for n in graph.nodes
                if n.kind == "DATASET_VERSION" and n.resource_id != key
            }
        )
        return FreshnessDependencies(
            statuses=[self.freshness(p, source) for source in source_ids[:100]],
            indexing_complete=graph.indexing.complete,
            truncated=graph.truncated or len(source_ids) > 100,
        )

    def observe(self, s: Session, p: Principal, row: ExecutionJob) -> ExecutionObservation:
        view = self.job_view(s, p, row)
        # Do not propagate arbitrary persisted error/metric strings.
        view.error = SAFE_ERRORS.get(row.error, "EXECUTION_FAILED") if row.error else None
        for n in view.nodes:
            if n.error:
                n.error = "NODE_FAILED"
        allowed_metrics = {
            "peak_memory_bytes",
            "temporary_bytes",
            "wall_seconds",
            "row_count",
            "output_rows",
            "source_bytes",
            "created",
            "updated",
            "preserved",
            "observed",
        }
        view.metrics = {
            k: v
            for k, v in view.metrics.items()
            if k in allowed_metrics and isinstance(v, (int, float)) and not isinstance(v, bool)
        }
        timelines = []
        visible_nodes = {n.node_id for n in view.nodes}
        for timeline in s.scalars(
            select(DAGNodeExecution)
            .where(
                DAGNodeExecution.tenant_id == p.tenant_id,
                DAGNodeExecution.job_id == row.id,
            )
            .order_by(DAGNodeExecution.node_id)
            .limit(100)
        ):
            if timeline.node_id not in visible_nodes:
                continue
            metrics = timeline.result.get("metrics", {})
            safe = (
                {
                    k: float(v)
                    for k, v in metrics.items()
                    if k in allowed_metrics and isinstance(v, (float, int))
                }
                if isinstance(metrics, dict)
                else {}
            )
            timelines.append(
                NodeTimeline(
                    node_id=timeline.node_id,
                    state=timeline.state,
                    attempt=timeline.attempt,
                    started_at=timeline.started_at,
                    completed_at=timeline.completed_at,
                    duration_seconds=max(
                        0.0, (timeline.completed_at - timeline.started_at).total_seconds()
                    )
                    if timeline.started_at and timeline.completed_at
                    else None,
                    error_category="NODE_FAILED" if timeline.error else None,
                    measured_metrics=safe,
                )
            )
        return ExecutionObservation(
            execution=view,
            node_timeline=timelines,
            duration_seconds=max(0.0, (row.completed_at - row.started_at).total_seconds())
            if row.completed_at and row.started_at
            else None,
            queue_delay_seconds=max(0.0, (row.started_at - row.created_at).total_seconds())
            if row.started_at
            else None,
            metric_status="MEASURED" if row.metrics else "UNAVAILABLE",
            error_category=SAFE_ERRORS.get(row.error, "EXECUTION_FAILED") if row.error else None,
        )

    def execution(self, p: Principal, key: UUID) -> ExecutionObservation:
        with self.scope(p) as s:
            return self.observe(s, p, self.job(s, p, key))

    def health(self, p: Principal, key: UUID, limit: int = 50, offset: int = 0) -> HealthSummary:
        from ontology_platform.branching.service import page

        page(limit, offset)
        with self.scope(p) as s:
            self.resource(s, p, key)
            rows = s.scalars(
                select(ExecutionJob)
                .where(ExecutionJob.tenant_id == p.tenant_id, ExecutionJob.resource_id == key)
                .order_by(ExecutionJob.created_at.desc(), ExecutionJob.id)
                .limit(limit + 1)
                .offset(offset)
            ).all()
            failures = 0
            for r in rows[:limit]:
                if r.state != "FAILED":
                    break
                failures += 1
            return HealthSummary(
                resource_id=key,
                executions=[self.observe(s, p, r) for r in rows[:limit]],
                consecutive_failures=failures,
                history_truncated=len(rows) > limit,
                last_success_id=next((r.id for r in rows[:limit] if r.state == "SUCCEEDED"), None),
                last_failure_id=next((r.id for r in rows[:limit] if r.state == "FAILED"), None),
                active_ids=[
                    r.id for r in rows[:limit] if r.state in {"ADMITTED", "RUNNING", "CANCELLING"}
                ],
            )

    def events(self, p: Principal, key: UUID, limit: int, offset: int) -> list[EventView]:
        from ontology_platform.branching.service import page

        page(limit, offset)
        with self.scope(p) as s:
            self.resource(s, p, key)
            cutoff = clock(s) - timedelta(days=90)
            return [
                EventView.model_validate(e)
                for e in s.scalars(
                    select(OperationalEvent)
                    .where(
                        OperationalEvent.tenant_id == p.tenant_id,
                        OperationalEvent.resource_id == key,
                        OperationalEvent.created_at >= cutoff,
                    )
                    .order_by(OperationalEvent.created_at.desc(), OperationalEvent.id)
                    .offset(offset)
                    .limit(limit)
                )
            ]

    def dashboard(self, p: Principal, days: int = 7) -> Dashboard:
        if not 1 <= days <= 30:
            raise ApplicationError("invalid_range", "Dashboard range must be 1–30 days", 422)
        with self.scope(p) as s:
            now = clock(s)
            # SQL membership pruning precedes the sample and every aggregate. No hidden counts.
            rows = s.scalars(
                select(ExecutionJob)
                .join(
                    Resource,
                    (ExecutionJob.tenant_id == Resource.tenant_id)
                    & (ExecutionJob.resource_id == Resource.id),
                )
                .where(
                    ExecutionJob.tenant_id == p.tenant_id,
                    self.visible(p),
                    Resource.state == "ACTIVE",
                    ExecutionJob.created_at >= now - timedelta(days=days),
                )
                .order_by(ExecutionJob.created_at.desc(), ExecutionJob.id)
                .limit(501)
            ).all()
            visible = []
            for row in rows[:500]:
                try:
                    self.resource(s, p, row.resource_id)
                    visible.append(row)
                except ApplicationError as exc:
                    if exc.status_code not in {403, 404}:
                        raise
            return Dashboard(
                checked_at=now,
                days=days,
                execution_counts=dict(Counter(r.state for r in visible)),
                recent_failures=[self.observe(s, p, r) for r in visible if r.state == "FAILED"][
                    :20
                ],
                sampled_resources=len({r.resource_id for r in visible}),
                truncated=len(rows) > 500,
            )

    def columns(
        self, p: Principal, key: UUID, version: UUID, output: str | None = None
    ) -> ColumnLineage:
        import polars as pl

        from ontology_platform.observability.columns import FrameLineage, apply, records
        from ontology_platform.observability.contracts import ColumnLineage
        from ontology_platform.pipelines.dag import DAGDefinition, topology
        from ontology_platform.pipelines.dag_service import read_bindings
        from ontology_platform.pipelines.engine import schema_dtype

        with self.scope(p) as s:
            definition = self.definition(s, p, key, version)
            if definition.specification.get("format_version") != 2:
                return ColumnLineage(
                    status="UNSUPPORTED",
                    reason="Historical source pins unavailable; inspect run provenance",
                    records=[],
                    inputs={},
                )
            spec = DAGDefinition.model_validate(definition.specification)
            read_bindings(self, s, p, spec)
            frames = {}
            bindings = {}
            try:
                for inp in spec.inputs:
                    logical = s.get(DatasetVersion, (p.tenant_id, inp.dataset_id, inp.version_id))
                    if logical is None or logical.state != "COMMITTED":
                        raise missing("Dataset version")
                    schema = {
                        c["name"]: schema_dtype(c["logical_type"])
                        for c in cast(list[dict[str, Any]], logical.result["schema"])
                    }
                    frames[inp.name] = FrameLineage(
                        pl.LazyFrame(schema=schema), {c: {(inp.name, c)} for c in schema}
                    )
                    bindings[inp.name] = node("DATASET_VERSION", inp.dataset_id, inp.version_id)
                for ident in topology(spec):
                    transform = next(n for n in spec.nodes if n.id == ident)
                    frames[ident] = apply(
                        transform.config,
                        frames[transform.inputs["input"]],
                        frames[transform.inputs["right"]] if "right" in transform.inputs else None,
                    )
                target = (
                    next((o for o in spec.outputs if o.id == output), None)
                    if output
                    else spec.outputs[0]
                )
                if target is None:
                    raise missing("Output")
                result, truncated = records(frames[target.source])
                return ColumnLineage(
                    status="PARTIAL" if truncated else "EXACT",
                    reason="Closed AST metadata; VALUE, ROW and ORDER dependencies are distinct",
                    records=result,
                    inputs=bindings,
                    truncated=truncated,
                )
            except (ValueError, KeyError, pl.exceptions.PolarsError):
                return ColumnLineage(
                    status="UNSUPPORTED",
                    reason="Source schema metadata cannot be planned",
                    records=[],
                    inputs={},
                )
