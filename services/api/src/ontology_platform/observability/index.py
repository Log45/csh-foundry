"""Bounded recoverable projection of canonical metadata. Never reads artifact bytes."""

import hashlib
import json
from typing import Any, cast
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.db.models import (
    ApplicationVersion,
    ArtifactVersion,
    AutomationReceipt,
    DAGPreparedOutput,
    DatasetVersion,
    ExecutionInput,
    ExecutionJob,
    FunctionInvocation,
    GovernedDefinition,
    LineageEdge,
    LineagePending,
    MappingDefinition,
    PipelineDefinition,
)
from ontology_platform.observability.contracts import LineageNode
from ontology_platform.pipelines.dag import DAGDefinition, topology


def node(
    kind: str, resource: UUID, version: UUID | None = None, local: str | None = None
) -> LineageNode:
    return LineageNode(
        key=":".join([kind, str(resource), str(version or ""), local or ""]),
        kind=kind,
        resource_id=resource,
        version_id=version,
        local_id=local,
    )


def ontology_node(
    kind: str, resource: UUID, ontology: str, version: str, entity: str
) -> LineageNode:
    """Unify canonical types across registry aliases; retain each reference ACL."""
    key = hashlib.sha256(
        json.dumps([ontology, version, entity], separators=(",", ":")).encode()
    ).hexdigest()
    return LineageNode(
        key=f"{kind}:{key}",
        kind=kind,
        resource_id=resource,
        local_id=entity,
        ontology_id=ontology,
        schema_version=version,
    )


def edge(
    s: Session,
    tenant: UUID,
    origin: UUID,
    a: LineageNode,
    b: LineageNode,
    relation: str,
    provenance: str,
    mode: str = "DESIGN",
    certainty: str = "EXACT_VERSION",
) -> None:
    identity = hashlib.sha256(
        json.dumps(
            [str(tenant), str(origin), a.key, b.key, relation, provenance, mode],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    s.execute(
        insert(LineageEdge)
        .values(
            tenant_id=tenant,
            id=identity,
            origin_id=origin,
            source_resource_id=a.resource_id,
            target_resource_id=b.resource_id,
            source_key=a.key,
            target_key=b.key,
            source=a.model_dump(mode="json"),
            target=b.model_dump(mode="json"),
            relation=relation,
            mode=mode,
            certainty=certainty,
            provenance=provenance,
        )
        .on_conflict_do_nothing()
    )


INDEX_PREFIX = "v1|"

SOURCES: list[tuple[str, Any, str]] = [
    ("artifact", ArtifactVersion, "artifact_id"),
    ("dataset", DatasetVersion, "artifact_id"),
    ("definition", PipelineDefinition, "pipeline_id"),
    ("mapping", MappingDefinition, "mapping_id"),
    ("application", ApplicationVersion, "application_id"),
    ("governed", GovernedDefinition, "resource_id"),
    ("run", ExecutionJob, "resource_id"),
]


def project_row(s: Session, tenant: UUID, resource: UUID, kind: str, row: Any) -> None:
    # Explicit canonical classes, not arbitrary user graph inserts.
    def put(
        a: LineageNode,
        b: LineageNode,
        relation: str,
        *,
        execution: bool = False,
        certainty: str | None = None,
    ) -> None:
        edge(
            s,
            tenant,
            resource,
            a,
            b,
            relation,
            f"{kind}:{row.id}",
            "EXECUTION" if execution else "DESIGN",
            certainty or ("HISTORICAL" if execution else "EXACT_VERSION"),
        )

    if isinstance(row, ArtifactVersion) and row.state == "COMMITTED":
        put(node("RESOURCE", resource), node("ARTIFACT_VERSION", resource, row.id), "HAS_VERSION")
    elif isinstance(row, DatasetVersion) and row.state == "COMMITTED":
        put(
            node("ARTIFACT_VERSION", resource, row.id),
            node("DATASET_VERSION", resource, row.id),
            "DERIVED_FROM",
        )
        put(node("RESOURCE", resource), node("DATASET_VERSION", resource, row.id), "HAS_VERSION")
    elif isinstance(row, PipelineDefinition):
        definition = node("PIPELINE_DEFINITION", resource, row.id)
        put(node("RESOURCE", resource), definition, "HAS_VERSION")
        if row.specification.get("format_version") == 2:
            spec = DAGDefinition.model_validate(row.specification)
            nodes = {
                i.name: node("DATASET_VERSION", i.dataset_id, i.version_id) for i in spec.inputs
            }
            for a in nodes.values():
                put(a, definition, "DEPENDS_ON")
            for ident in topology(spec):
                transform = next(n for n in spec.nodes if n.id == ident)
                target = node("TRANSFORM_NODE", resource, row.id, ident)
                for parent in sorted(set(transform.inputs.values())):
                    put(nodes[parent], target, "TRANSFORMS")
                put(definition, target, "CONTAINS")
                nodes[ident] = target
            for output in spec.outputs:
                if output.dataset_id:
                    put(
                        nodes[output.source],
                        node("RESOURCE", output.dataset_id),
                        "DEPENDS_ON",
                        certainty="POTENTIAL",
                    )
    elif isinstance(row, MappingDefinition):
        definition = node("MAPPING_DEFINITION", resource, row.id)
        put(node("RESOURCE", resource), definition, "HAS_VERSION")
        for obj in cast(list[dict[str, Any]], row.specification.get("objects", [])):
            put(
                definition,
                ontology_node(
                    "ONTOLOGY_OBJECT_TYPE",
                    row.target_resource_id,
                    row.ontology_id,
                    row.schema_version,
                    obj["object_type"],
                ),
                "BINDS_TO",
            )
        for link in cast(list[dict[str, Any]], row.specification.get("relationships", [])):
            put(
                definition,
                ontology_node(
                    "ONTOLOGY_LINK_TYPE",
                    row.target_resource_id,
                    row.ontology_id,
                    row.schema_version,
                    link["link_type"],
                ),
                "BINDS_TO",
            )
    elif isinstance(row, ApplicationVersion):
        version = node("APPLICATION_VERSION", resource, row.id)
        put(node("RESOURCE", resource), version, "HAS_VERSION")
        from ontology_platform.applications.contracts import Document

        doc = Document.model_validate(row.document)
        dependencies = {dep.id: dep for dep in doc.dependencies}
        for dep in doc.dependencies:
            put(node("RESOURCE", dep.resource_id), version, "DEPENDS_ON")
        for source in doc.sources:
            dep = dependencies[source.dependency]
            put(
                ontology_node(
                    "ONTOLOGY_OBJECT_TYPE",
                    dep.resource_id,
                    dep.ontology_id,
                    dep.schema_version,
                    source.query.object_type,
                ),
                version,
                "BINDS_TO",
                certainty="POTENTIAL",
            )
        for action in doc.actions:
            dep = dependencies[action.dependency]
            put(
                ontology_node(
                    "ACTION", dep.resource_id, dep.ontology_id, dep.schema_version, action.action_id
                ),
                version,
                "INVOKES",
            )
    elif isinstance(row, GovernedDefinition) and row.kind == "FUNCTION":
        put(
            node("RESOURCE", resource), node("FUNCTION_DEFINITION", resource, row.id), "HAS_VERSION"
        )
    elif isinstance(row, GovernedDefinition) and row.kind == "AUTOMATION":
        version = node("AUTOMATION", resource, row.id)
        put(node("RESOURCE", resource), version, "HAS_VERSION")
        if row.target_resource_id:
            put(
                version,
                node("FUNCTION_DEFINITION", row.target_resource_id, row.target_definition_id),
                "INVOKES",
            )
        if row.event_resource_id:
            put(node("RESOURCE", row.event_resource_id), version, "TRIGGERS", certainty="RESOURCE")
    elif isinstance(row, ExecutionJob):
        run = node("EXECUTION", resource, row.id)
        put(node("RESOURCE", resource), run, "HAS_EXECUTION", execution=True)
        if row.state == "SUCCEEDED":
            for inp in s.scalars(
                select(ExecutionInput)
                .where(ExecutionInput.tenant_id == tenant, ExecutionInput.job_id == row.id)
                .order_by(ExecutionInput.name)
                .limit(16)
            ):
                put(
                    node("DATASET_VERSION", inp.dataset_id, inp.version_id),
                    run,
                    "CONSUMES",
                    execution=True,
                )
            if row.definition_id:
                put(
                    node("PIPELINE_DEFINITION", resource, row.definition_id),
                    run,
                    "EXECUTES",
                    execution=True,
                )
            if row.output_dataset_id and row.output_version_id:
                put(
                    run,
                    node("DATASET_VERSION", row.output_dataset_id, row.output_version_id),
                    "PRODUCES",
                    execution=True,
                )
            for published in s.scalars(
                select(DAGPreparedOutput)
                .where(
                    DAGPreparedOutput.tenant_id == tenant,
                    DAGPreparedOutput.job_id == row.id,
                    DAGPreparedOutput.state == "COMMITTED",
                )
                .order_by(DAGPreparedOutput.output_id)
                .limit(16)
            ):
                put(
                    run,
                    node("DATASET_VERSION", published.dataset_id, published.version_id),
                    "PRODUCES",
                    execution=True,
                )
                published_definition = s.get(
                    PipelineDefinition, (tenant, resource, row.definition_id)
                )
                if (
                    published_definition is not None
                    and published_definition.specification.get("format_version") == 2
                ):
                    executed = DAGDefinition.model_validate(published_definition.specification)
                    declared = next(o for o in executed.outputs if o.id == published.output_id)
                    input_source = next(
                        (i for i in executed.inputs if i.name == declared.source), None
                    )
                    contributing = (
                        node("DATASET_VERSION", input_source.dataset_id, input_source.version_id)
                        if input_source
                        else node(
                            "TRANSFORM_NODE", resource, published_definition.id, declared.source
                        )
                    )
                    put(
                        contributing,
                        node("DATASET_VERSION", published.dataset_id, published.version_id),
                        "DERIVED_FROM",
                        execution=True,
                    )

        if row.kind == "FUNCTION":
            invocation = s.get(FunctionInvocation, (tenant, row.id))
            if invocation is not None and row.started_at is not None:
                put(
                    node("FUNCTION_DEFINITION", invocation.function_id, invocation.definition_id),
                    run,
                    "EXECUTES",
                    execution=True,
                )
            for receipt in s.scalars(
                select(AutomationReceipt)
                .where(AutomationReceipt.tenant_id == tenant, AutomationReceipt.job_id == row.id)
                .order_by(AutomationReceipt.id)
                .limit(16)
            ):
                put(
                    node("AUTOMATION", receipt.automation_id, receipt.definition_id),
                    run,
                    "TRIGGERS",
                    execution=True,
                )
        if row.mapping_definition_id:
            mapping_def = s.get(MappingDefinition, (tenant, resource, row.mapping_definition_id))
            if mapping_def:
                put(
                    node("MAPPING_DEFINITION", resource, mapping_def.id),
                    run,
                    "EXECUTES",
                    execution=True,
                )
                # Durable records establish affected types, including partial runs.
                from ontology_platform.db.models import MaterializationRecord

                targets = s.execute(
                    select(
                        MaterializationRecord.target["type"].astext,
                        MaterializationRecord.target["link_type"].astext,
                    )
                    .where(
                        MaterializationRecord.tenant_id == tenant,
                        MaterializationRecord.run_id == row.id,
                    )
                    .distinct()
                    .limit(100)
                )
                for actual_type, actual_link in targets:
                    object_type = actual_type or actual_link
                    if object_type:
                        for consumed in s.scalars(
                            select(ExecutionInput)
                            .where(
                                ExecutionInput.tenant_id == tenant, ExecutionInput.job_id == row.id
                            )
                            .limit(16)
                        ):
                            put(
                                node("DATASET_VERSION", consumed.dataset_id, consumed.version_id),
                                run,
                                "CONSUMES",
                                execution=True,
                            )
                        put(
                            run,
                            ontology_node(
                                "ONTOLOGY_OBJECT_TYPE"
                                if actual_type is not None
                                else "ONTOLOGY_LINK_TYPE",
                                mapping_def.target_resource_id,
                                mapping_def.ontology_id,
                                mapping_def.schema_version,
                                object_type,
                            ),
                            "MATERIALIZES_INTO",
                            execution=True,
                        )


def reconcile(s: Session, pending: LineagePending, batch: int = 50) -> bool:
    if not 1 <= batch <= 100:
        raise ValueError("Backfill batch must be between 1 and 100")
    position = (
        pending.cursor[len(INDEX_PREFIX) :] if pending.cursor.startswith(INDEX_PREFIX) else ""
    )
    pending.cursor = INDEX_PREFIX + position
    candidates: list[tuple[str, str, Any]] = []
    for kind, model, field in SOURCES:
        # A bounded merge of independently keyset-paginated authoritative tables.
        prefix = kind + ":"
        from sqlalchemy import String, cast, literal

        cursor_key = literal(prefix) + cast(model.id, String)
        rows = s.scalars(
            select(model)
            .where(
                model.tenant_id == pending.tenant_id,
                getattr(model, field) == pending.resource_id,
                cursor_key > position,
            )
            .order_by(model.id)
            .limit(batch + 1)
        )
        candidates.extend((prefix + str(r.id), kind, r) for r in rows)
    candidates.sort(key=lambda x: x[0])
    for key, kind, row in candidates[:batch]:
        project_row(s, pending.tenant_id, pending.resource_id, kind, row)
        pending.cursor = INDEX_PREFIX + key
    complete = len(candidates) <= batch
    if complete:
        pending.indexed_generation = pending.generation
    s.flush()
    return complete


def tick(sessions: sessionmaker[Session]) -> None:
    # The existing trusted controller calls this; no independent scheduler or queue.
    with sessions.begin() as s:
        s.execute(
            text("""DELETE FROM operational_events WHERE (tenant_id,id) IN
          (SELECT tenant_id,id FROM operational_events WHERE created_at < now()-interval '90 days'
           ORDER BY created_at,id LIMIT 500)""")
        )
        rows = s.scalars(
            select(LineagePending)
            .where(
                or_(
                    LineagePending.generation != LineagePending.indexed_generation,
                    ~LineagePending.cursor.startswith(INDEX_PREFIX),
                )
            )
            .order_by(LineagePending.updated_at, LineagePending.resource_id)
            .limit(4)
            .with_for_update(skip_locked=True)
        ).all()
        for pending in rows:
            reconcile(s, pending)
