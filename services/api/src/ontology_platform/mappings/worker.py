"""Mapping adapter for the shared fenced execution controller."""

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ontology_platform.contracts import CreateObject, LinkInput
from ontology_platform.db.models import (
    ExecutionInput,
    ExecutionJob,
    Link,
    MappingDefinition,
    MappingOwnership,
    MaterializationRecord,
    Object,
)
from ontology_platform.db.session import clock
from ontology_platform.edits.service import ReconciliationService, SourceUpdate
from ontology_platform.errors import ApplicationError
from ontology_platform.execution.config import ExecutionSettings
from ontology_platform.execution.isolation import isolated
from ontology_platform.mappings.contracts import MappingRun, MappingSpec
from ontology_platform.mappings.service import MappingService
from ontology_platform.objects.service import ObjectService
from ontology_platform.security.interfaces import Principal


def adapter(worker: Any) -> MappingService:
    svc = worker.service
    return MappingService(svc.sessions, svc.authorizer, svc.settings, svc.store)


def authorize(worker: Any, s: Session, p: Principal, job: ExecutionJob) -> list[Any]:
    svc = adapter(worker)
    svc.artifact(s, p, job.resource_id, True)
    assert job.mapping_definition_id is not None
    definition = svc.definition(s, p, job.resource_id, job.mapping_definition_id)
    spec = MappingSpec.model_validate(definition.specification)
    svc.target(s, p, spec, True)
    body = MappingRun.model_validate(
        {k: job.request[k] for k in ("definition_id", "dataset_id", "version_id", "mode")}
    )
    logical, physical = svc.inputs(s, p, body, spec)
    source = s.get(ExecutionInput, (p.tenant_id, job.id, "source"))
    if (
        source is None
        or source.checksum != physical.checksum
        or job.request["schema"] != logical.result["schema"]
    ):
        raise ApplicationError("invalid_input", "Immutable input pin mismatch", 409)
    return [physical]


def object_operation(
    svc: MappingService,
    s: Session,
    p: Principal,
    job: ExecutionJob,
    spec: MappingSpec,
    value: dict[str, Any],
    mutate: bool,
) -> str:
    key = (p.tenant_id, spec.ontology_id, value["type"], value["id"])
    ownership = s.get(MappingOwnership, key)
    objects = ObjectService(svc.sessions, svc.authorizer, session=s)
    current_row = s.get(Object, key)
    if ownership is not None and ownership.mapping_id != job.resource_id:
        raise ApplicationError("mapping_ownership", "Target ownership conflicts", 409)
    if current_row is not None and ownership is None:
        raise ApplicationError("mapping_ownership", "Existing object cannot be adopted", 409)
    if current_row is None and ownership is not None:
        raise ApplicationError("mapping_ownership", "Governed deletion prevents recreation", 409)
    if current_row is None:
        if mutate:
            reconcile = ReconciliationService(svc.sessions, svc.authorizer, session=s)
            reconcile.create_from_source(
                p,
                spec.ontology_id,
                CreateObject(
                    object_type_id=value["type"],
                    object_id=value["id"],
                    properties=value["properties"],
                ),
                "mapping:" + str(job.resource_id),
                owner="pipeline",
            )
            s.add(
                MappingOwnership(
                    tenant_id=p.tenant_id,
                    ontology_id=spec.ontology_id,
                    object_type=value["type"],
                    object_id=value["id"],
                    mapping_id=job.resource_id,
                )
            )
        return "created"
    current = objects.get(p, spec.ontology_id, value["type"], value["id"])
    if spec.write_policy == "insert_only" and any(
        current.properties.get(k) != v for k, v in value["properties"].items()
    ):
        raise ApplicationError("mapping_conflict", "Insert-only values differ", 409)
    if not mutate:
        return "observed"
    result = ReconciliationService(svc.sessions, svc.authorizer, session=s).refresh(
        p,
        spec.ontology_id,
        value["type"],
        value["id"],
        SourceUpdate(
            source="mapping:" + str(job.resource_id),
            owner="pipeline",
            expected_version=current.version,
            properties=value["properties"],
            policy="edit_wins",
        ),
    )
    return "updated" if result.object.version != current.version else "preserved"


def link_operation(
    svc: MappingService,
    s: Session,
    p: Principal,
    spec: MappingSpec,
    value: dict[str, Any],
    mutate: bool,
    staged: sqlite3.Connection,
) -> str:
    objects = ObjectService(svc.sessions, svc.authorizer, session=s)
    svc.authorizer.require(
        p, "link:read", f"{p.tenant_id}/{spec.ontology_id}/links/{value['link_type']}"
    )
    from ontology_platform.metadata.storage import active_definition
    from ontology_platform.objects.relationships import link_type

    schema = active_definition(s, svc.ontology(s, p, spec.ontology_id, write=mutate))
    typed = link_type(schema, value["link_type"])
    for direction, restricted in (
        ("source", typed.cardinality in {"one_to_one", "many_to_one"}),
        ("target", typed.cardinality in {"one_to_one", "one_to_many"}),
    ):
        if restricted:
            other = "target" if direction == "source" else "source"
            existing = s.scalar(
                select(Link)
                .where(
                    Link.tenant_id == p.tenant_id,
                    Link.ontology_id == spec.ontology_id,
                    Link.link_type_id == typed.id,
                    getattr(Link, direction + "_object_id") == value[direction + "_id"],
                    getattr(Link, other + "_object_id") != value[other + "_id"],
                )
                .limit(1)
            )
            if existing is not None:
                raise ApplicationError("cardinality_conflict", "Link cardinality conflicts", 409)
    for kind in ("source", "target"):
        try:
            objects.get(p, spec.ontology_id, value[kind + "_type"], value[kind + "_id"])
        except ApplicationError as exc:
            if exc.code != "not_found" or mutate:
                raise
            from ontology_platform.mappings.engine import target_key

            pending = target_key(
                {"kind": "object", "type": value[kind + "_type"], "id": value[kind + "_id"]}
            )
            if staged.execute("SELECT 1 FROM targets WHERE key=?", (pending,)).fetchone() is None:
                raise ApplicationError(
                    "mapping_endpoint", "Required endpoint is unavailable", 409
                ) from exc
    key = (
        p.tenant_id,
        spec.ontology_id,
        value["link_type"],
        value["source_type"],
        value["source_id"],
        value["target_type"],
        value["target_id"],
    )
    edge = s.get(Link, key)
    if edge is not None:
        return "observed"
    # Canonical links have no edit-overlay tombstone. Immutable prior observations detect
    # governed removal without introducing a second relationship store or resurrecting an edge.
    from ontology_platform.mappings.engine import target_key

    previous = s.scalar(
        select(MaterializationRecord.run_id)
        .join(
            ExecutionJob,
            (ExecutionJob.tenant_id == MaterializationRecord.tenant_id)
            & (ExecutionJob.id == MaterializationRecord.run_id),
        )
        .join(
            MappingDefinition,
            (MappingDefinition.tenant_id == ExecutionJob.tenant_id)
            & (MappingDefinition.mapping_id == ExecutionJob.resource_id)
            & (MappingDefinition.id == ExecutionJob.mapping_definition_id),
        )
        .where(
            MaterializationRecord.tenant_id == p.tenant_id,
            MaterializationRecord.target_key == target_key(value),
            MappingDefinition.ontology_id == spec.ontology_id,
        )
        .limit(1)
    )
    if previous is not None:
        raise ApplicationError(
            "mapping_link_conflict", "Governed link removal prevents recreation", 409
        )
    if mutate:
        objects.create_link(
            p,
            spec.ontology_id,
            LinkInput(
                link_type_id=value["link_type"],
                source_object_type_id=value["source_type"],
                source_object_id=value["source_id"],
                target_object_type_id=value["target_type"],
                target_object_id=value["target_id"],
            ),
        )
    return "created"


def execute(
    worker: Any, tenant: UUID, key: UUID, token: UUID, p: Principal, limits: ExecutionSettings
) -> None:
    svc = adapter(worker)
    with svc.scope(p) as s:
        job = worker.fenced(s, tenant, key, token)
        physical = authorize(worker, s, p, job)[0]
        assert job.mapping_definition_id is not None
        definition = svc.definition(s, p, job.resource_id, job.mapping_definition_id)
        spec = MappingSpec.model_validate(definition.specification)
        schema = svc.target(s, p, spec, True)
        logical = svc.datasets().record(s, p, physical.artifact_id, physical.id)
        request = {
            "specification": spec.model_dump(mode="json"),
            "ontology": schema.model_dump(mode="json"),
            "format": logical.format,
            "row_count": logical.result["row_count"],
        }
        mode = job.request["mode"]
        job.state, job.started_at = "RUNNING", clock(s)
        s.expunge(physical)
    with tempfile.TemporaryDirectory(prefix="foundry-mapping-") as temporary:
        directory = Path(temporary)
        path = directory / "source"

        def renew() -> bool:
            return bool(worker.heartbeat(tenant, key, token))

        worker.spool(physical, path, limits, renew)
        result = isolated("mapping", request | {"path": str(path)}, directory, limits, renew)
        metrics = {k: v for k, v in result.items() if k not in {"preview", "metrics"}} | result.get(
            "metrics", {}
        )
        if "error" in result or result.get("invalid_records"):
            worker.fail(
                tenant,
                key,
                token,
                str(result.get("error", "invalid_mapping_records")),
                False,
                metrics,
            )
            return
        with sqlite3.connect(directory / "mapping.sqlite") as staged:
            staged.execute("PRAGMA cache_size=-2048")
            # Full-source conversion/duplicate validation precedes any mutation. Preflight checks
            # ownership and endpoints; commit-time domain invariants remain authoritative.
            for mutate in (False, True):
                if mutate and mode == "full_validation":
                    break
                for kind in ("object", "link"):
                    cursor = staged.execute(
                        "SELECT key,payload,record FROM targets WHERE kind=? ORDER BY key", (kind,)
                    )
                    while batch := cursor.fetchmany(100):
                        with svc.scope(p) as s:
                            job = worker.fenced(s, tenant, key, token)
                            authorize(worker, s, p, job)
                            s.execute(
                                text("SELECT set_config('foundry.execution_token', :token, true)"),
                                {"token": str(token)},
                            )
                            counts = dict(job.metrics)
                            for target, payload, record in batch:
                                if (
                                    mutate
                                    and s.get(MaterializationRecord, (tenant, key, target))
                                    is not None
                                ):
                                    continue
                                value = json.loads(payload)
                                operation = (
                                    object_operation(svc, s, p, job, spec, value, mutate)
                                    if kind == "object"
                                    else link_operation(svc, s, p, spec, value, mutate, staged)
                                )
                                if mutate:
                                    s.add(
                                        MaterializationRecord(
                                            tenant_id=tenant,
                                            run_id=key,
                                            target_key=target,
                                            target={
                                                k: v for k, v in value.items() if k != "properties"
                                            },
                                            source_record=record,
                                            operation=operation,
                                        )
                                    )
                                    counts[operation] = int(counts.get(operation, 0)) + 1
                            if mutate:
                                job.metrics = counts | {
                                    "publication": "visible-transactional-batches"
                                }
                            s.flush()
                            worker.fenced(s, tenant, key, token)  # Reject expiry during a batch.
        with svc.scope(p) as s:
            job = worker.fenced(s, tenant, key, token)
            authorize(worker, s, p, job)
            job.metrics = (
                dict(job.metrics)
                | metrics
                | {"mode": mode, "publication": "visible-transactional-batches"}
            )
            job.error = None
            job.state, job.completed_at = "SUCCEEDED", clock(s)
            job.token, job.lease_until = None, None
            svc.audit(s, p, "materialization_succeeded", job.id)
