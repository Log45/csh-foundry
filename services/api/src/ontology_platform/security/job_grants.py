"""Durable job authority intersected with live subject and authenticated worker authority.

No credentials are persisted. Contexts are immutable values local to an attempt; the grant
and job state are read again in each governed transaction under the security revision lock.
"""

from datetime import timedelta
from time import monotonic
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ontology_platform.db.models import (
    DAGPreparedOutput,
    ExecutionInput,
    ExecutionJob,
    IngestionMapping,
    IngestionRun,
    IngestionSource,
    IngestionStage,
    JobExecutionGrant,
    MappingDefinition,
    PipelineDefinition,
    PlatformPrincipal,
    Resource,
    SemanticArtifact,
    SemanticJob,
)
from ontology_platform.db.session import clock
from ontology_platform.errors import ApplicationError
from ontology_platform.security.audit import persist_audit
from ontology_platform.security.interfaces import Principal

Job = IngestionRun | SemanticJob | ExecutionJob
READ = {"schema:read", "object:read", "object:query", "property:read", "link:read"}
INGESTION = READ | {
    "source:read",
    "mapping:read",
    "source:use_binding",
    "ingestion:history",
    "ingestion:claim",
    "ingestion:execute",
    "object:create",
    "object:update",
    "object:delete",
    "object:link",
    "property:update",
    "link:create",
    "link:delete",
    "edit:initialize_source",
    "edit:reconcile",
    "edit:override",
    "edit:resolve",
}
SEMANTIC = READ | {
    "semantic:execute",
    "semantic:claim",
    "semantic:read",
    "semantic:export",
    "source:read",
    "ingestion:history",
}
EXECUTION = READ | {"project:read", "project:write"}


def forbidden() -> ApplicationError:
    return ApplicationError(
        "job_authorization_denied", "Job grant or current authority unavailable", 403
    )


def binding(kind: str) -> Any:
    return getattr(
        JobExecutionGrant,
        {"ingestion": "ingestion_id", "semantic": "semantic_id", "execution": "execution_id"}[kind],
    )


def find(s: Session, tenant: UUID, kind: str, key: UUID) -> JobExecutionGrant | None:
    return s.scalar(
        select(JobExecutionGrant).where(
            JobExecutionGrant.tenant_id == tenant,
            binding(kind) == key,
        )
    )


def job_row(s: Session, p: Principal, *, lock: bool = False) -> Job:
    model: Any = {
        "ingestion": IngestionRun,
        "semantic": SemanticJob,
        "execution": ExecutionJob,
    }.get(p.job_kind or "")
    if model is None or p.job_id is None:
        raise forbidden()
    criteria = [model.tenant_id == p.tenant_id, model.id == p.job_id]
    if model is not ExecutionJob:
        criteria.append(model.ontology_id == p.delegation_ontology)
    row = s.scalar(
        select(model).where(*criteria).with_for_update(read=True)
        if lock
        else select(model).where(*criteria)
    )
    if row is None:
        raise forbidden()
    return cast(Job, row)


def create(s: Session, auth: Any, p: Principal, row: Job) -> None:
    from ontology_platform.security.service import PlatformAuthorizer

    if not isinstance(auth, PlatformAuthorizer):
        return  # Explicit trusted local development only; never used by the OIDC runtime.
    if p.authentication_method == "job":
        raise forbidden()  # A bounded grant cannot mint another grant.
    auth.identity(s, p)
    kind = (
        "execution"
        if isinstance(row, ExecutionJob)
        else ("ingestion" if isinstance(row, IngestionRun) else "semantic")
    )
    ontology = None if isinstance(row, ExecutionJob) else row.ontology_id
    resources: set[str] = set()
    projects: set[str] = set()
    ontologies = {ontology} if ontology else set()
    operations = INGESTION if kind == "ingestion" else SEMANTIC
    if isinstance(row, IngestionRun):
        resources.add(f"ingestion/runs/{row.id}")
        from ontology_platform.db.models import Version
        from ontology_platform.ingestion.contracts import MappingInput, SourceInput
        from ontology_platform.metadata.storage import definition_of

        version = s.get(Version, (p.tenant_id, ontology, row.schema_version))
        assert version is not None
        schema = definition_of(version)
        for ref in row.plan:
            assert isinstance(ref, dict)
            mapping = s.get(IngestionMapping, (p.tenant_id, ontology, ref["id"], ref["version"]))
            assert mapping is not None
            spec = MappingInput.model_validate_json(mapping.definition_json)
            source = s.get(
                IngestionSource, (p.tenant_id, ontology, mapping.source_id, mapping.source_version)
            )
            assert source is not None
            config = SourceInput.model_validate_json(source.definition_json)
            resources.update(
                {
                    f"sources/{source.id}",
                    f"mappings/{mapping.id}",
                    f"source-bindings/{config.binding}",
                    f"objects/{spec.object_type}",
                }
            )
            for relationship in spec.relationships:
                link = next(t for t in schema.link_types if t.id == relationship.link)
                resources.update({f"links/{link.id}", f"objects/{link.target_type}"})
    if isinstance(row, SemanticJob):
        for key in (row.primary_artifact, row.secondary_artifact):
            resources.add(f"semantic/artifacts/{key}")
            artifact = s.get(SemanticArtifact, (p.tenant_id, ontology, key))
            assert artifact is not None
            import json

            provenance = json.loads(artifact.manifest_json).get("provenance", {})
            for typed, keys in provenance.get("selected", {}).items():
                resources.add(f"objects/{typed}")
                # Public provenance truncates its merged list at 100. Fresh access still
                # checks the bounded 101 refs per selected type, so bind that same server-side
                # projection rather than broadening to all ingestion history or losing ref 101.
                for run_id in s.scalars(
                    select(IngestionStage.run_id)
                    .where(
                        IngestionStage.tenant_id == p.tenant_id,
                        IngestionStage.ontology_id == ontology,
                        IngestionStage.object_type == typed,
                        IngestionStage.object_id.in_(keys),
                        IngestionStage.state == "DONE",
                    )
                    .distinct()
                    .order_by(IngestionStage.run_id)
                    .limit(101)
                ):
                    resources.add(f"ingestion/runs/{run_id}")
            ingestion = provenance.get("ingestion", {})
            for source in ingestion.get("source_versions", []):
                resources.add(f"sources/{source[0]}")
            for run_id in ingestion.get("available_ingestion_runs", []):
                resources.add(f"ingestion/runs/{run_id}")
        # Link authorization also checks endpoint row/property policies during snapshotting.
        resources.add("links")
    if isinstance(row, ExecutionJob):
        s.flush()  # Include all immutable input and output reservations in this transaction.
        operations = EXECUTION | (INGESTION if row.kind == "MATERIALIZATION" else set())
        resources.add(str(row.resource_id))
        projects.add(str(row.project_id))
        if row.output_dataset_id:
            resources.add(str(row.output_dataset_id))
        for item in s.scalars(
            select(ExecutionInput).where(
                ExecutionInput.tenant_id == p.tenant_id,
                ExecutionInput.job_id == row.id,
            )
        ):
            resources.add(str(item.dataset_id))
        # Immutable definitions/plans contain governed bindings; scalar function inputs are
        # deliberately excluded and never interpreted as resource authority.
        data: list[Any] = []
        if row.definition_id:
            definition = s.get(
                PipelineDefinition, (p.tenant_id, row.resource_id, row.definition_id)
            )
            if definition:
                data.append(definition.specification)
        if row.mapping_definition_id:
            mapping_definition = s.get(
                MappingDefinition, (p.tenant_id, row.resource_id, row.mapping_definition_id)
            )
            if mapping_definition:
                data.append(mapping_definition.specification)
                ontologies.add(mapping_definition.ontology_id)
                from ontology_platform.mappings.contracts import MappingSpec

                spec_mapping = MappingSpec.model_validate(mapping_definition.specification)
                resources.add(str(spec_mapping.target_resource_id))
                scope = f"scope:{spec_mapping.ontology_id}/"
                resources.update(
                    scope + "objects/" + item.object_type for item in spec_mapping.objects
                )
                for edge in spec_mapping.relationships:
                    resources.update(
                        {
                            scope + "links/" + edge.link_type,
                            scope + "objects/" + edge.source.object_type,
                            scope + "objects/" + edge.target.object_type,
                        }
                    )
        automation = row.request.get("automation")
        if isinstance(automation, dict):
            resources.add(str(automation["resource_id"]))

        for value in data:
            if isinstance(value, dict) and value.get("format_version") == 2:
                from ontology_platform.pipelines.dag import DAGDefinition

                dag = DAGDefinition.model_validate(value.get("specification", value))
                resources.update(str(item.dataset_id) for item in dag.inputs)
                for target in dag.outputs:
                    if target.dataset_id:
                        resources.add(str(target.dataset_id))
                    if target.project_id:
                        projects.add(str(target.project_id))
        for output in s.scalars(
            select(DAGPreparedOutput).where(
                DAGPreparedOutput.tenant_id == p.tenant_id,
                DAGPreparedOutput.job_id == row.id,
            )
        ):
            resources.add(str(output.dataset_id))
        for resource_id in resources:
            if resource_id.startswith("scope:"):
                continue
            resource = s.get(Resource, (p.tenant_id, UUID(resource_id)))
            if resource:
                projects.add(str(resource.project_id))
    grant = JobExecutionGrant(
        id=uuid4(),
        tenant_id=p.tenant_id,
        principal_id=p.principal_id,
        ontology_id=ontology,
        ingestion_id=row.id if kind == "ingestion" else None,
        semantic_id=row.id if kind == "semantic" else None,
        execution_id=row.id if kind == "execution" else None,
        operations=sorted(operations & auth.permissions(s, p)),
        resources=sorted(resources),
        projects=sorted(projects),
        ontologies=sorted(ontologies),
        worker_permission=f"{kind}:claim",
        expires_at=clock(s) + timedelta(days=7),
    )
    s.add(grant)
    s.flush()
    audit(s, p, row.id, grant.id, "job:grant_created")


def audit(s: Session, p: Principal, key: UUID, grant: UUID | None, event: str) -> None:
    import hashlib

    from ontology_platform.db.models import AuthorizationAudit

    persist_audit(
        s,
        [
            AuthorizationAudit(
                id=uuid4(),
                tenant_id=p.tenant_id,
                principal_id=p.principal_id,
                actor_id=p.actor_id,
                job_id=key,
                execution_grant_id=grant,
                execution_token=p.execution_token,
                operation=event,
                resource_hash=hashlib.sha256(str(key).encode()).hexdigest(),
                allowed=not event.endswith("denied"),
                category="delegation",
                policy_version=0,
            )
        ],
    )


def context(
    s: Session, auth: Any, actor: Principal, kind: str, key: UUID, token: UUID | None = None
) -> Principal:
    if actor.authentication_method == "job":
        if (actor.job_id, actor.job_kind) != (key, kind) or (
            token is not None and actor.execution_token != token
        ):
            raise forbidden()
        return actor
    if actor.principal_type != "service" or actor.authentication_method not in {"oidc", "test"}:
        raise forbidden()
    auth.identity(s, actor)
    grant = find(s, actor.tenant_id, kind, key)
    if grant is None:
        raise ApplicationError(
            "job_grant_missing", "Legacy job requires authorized resubmission", 403
        )
    subject = s.get(PlatformPrincipal, grant.principal_id)
    if subject is None:
        raise forbidden()
    return actor.model_copy(
        update={
            "principal_id": subject.id,
            "principal_type": subject.principal_type,
            "authentication_method": "job",
            "actor_id": actor.principal_id,
            "job_id": key,
            "job_kind": kind,
            "execution_grant_id": grant.id,
            "delegation_ontology": grant.ontology_id,
            "execution_token": token,
        }
    )


def worker(p: Principal) -> Principal:
    if not p.actor_id:
        raise forbidden()
    return p.model_copy(
        update={
            "principal_id": p.actor_id,
            "principal_type": "service",
            "authentication_method": "oidc",
            "actor_id": None,
            "job_id": None,
            "job_kind": None,
            "execution_grant_id": None,
            "execution_token": None,
        }
    )


def validate(
    s: Session, auth: Any, p: Principal, resource: str, operation: str | None = None
) -> Principal:
    if p.job_kind not in {"ingestion", "semantic", "execution"} or p.execution_grant_id is None:
        raise forbidden()
    snapshot = auth.snapshot.get()
    cached = snapshot.job_bindings.get(p.execution_grant_id) if snapshot is not None else None
    if cached is None:
        row = job_row(s, p, lock=True)
        grant = s.scalar(
            select(JobExecutionGrant)
            .where(JobExecutionGrant.id == p.execution_grant_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if grant is None:
            raise forbidden()
        if snapshot is not None:
            snapshot.job_bindings[grant.id] = (row, grant)
    else:
        row, grant = cached
    if snapshot is None:
        now = clock(s)
    else:
        if snapshot.job_clock is None:
            snapshot.job_clock = (clock(s), monotonic())
        instant, anchor = snapshot.job_clock
        now = instant + timedelta(seconds=monotonic() - anchor)
    if (
        grant is None
        or grant.tenant_id != p.tenant_id
        or grant.principal_id != p.principal_id
        or getattr(grant, f"{p.job_kind}_id") != p.job_id
        or grant.revoked_at is not None
        or grant.expires_at <= now
    ):
        raise forbidden()
    if isinstance(row, ExecutionJob):
        if row.state not in {"QUEUED", "ADMITTED", "RUNNING"}:
            raise forbidden()
    elif row.status not in {"PENDING", "RUNNING"} or row.principal_id != p.principal_id:
        raise forbidden()
    if p.execution_token is not None and (
        row.token != p.execution_token or row.lease_until is None or row.lease_until <= now
    ):
        raise ApplicationError("lease_lost", "Execution context is fenced", 409)
    actor = worker(p)
    auth.identity(s, actor)
    permissions = auth.permissions(s, actor)
    if (
        "worker:delegate" not in permissions
        or grant.worker_permission not in permissions
        or (
            operation is not None
            and (operation not in grant.operations or operation not in permissions)
        )
    ):
        raise forbidden()
    parts = resource.split("/")
    if not parts or parts[0] != str(p.tenant_id):
        raise forbidden()
    if len(parts) > 1 and parts[1] == "projects":
        if len(parts) > 2 and parts[2] not in grant.projects:
            raise forbidden()
    elif len(parts) < 2 or parts[1] not in grant.ontologies:
        raise forbidden()
    if isinstance(row, ExecutionJob) and len(parts) > 2 and parts[2] in {"objects", "links"}:
        path = "scope:" + "/".join(parts[1:])
        if not any(path == prefix or path.startswith(prefix + "/") for prefix in grant.resources):
            raise forbidden()
    if not isinstance(row, ExecutionJob) and len(parts) > 2:
        path = "/".join(parts[2:])
        restricted = parts[2] in {"objects", "links", "sources", "mappings", "source-bindings"}
        restricted |= path.startswith(("semantic/artifacts/", "ingestion/runs/"))
        if restricted and not any(
            path == prefix or path.startswith(prefix + "/") for prefix in grant.resources
        ):
            raise forbidden()
        if (
            p.job_kind == "ingestion"
            and parts[2] == "ingestion"
            and len(parts) > 4
            and parts[4] != str(row.id)
        ):
            raise forbidden()
        if parts[2:4] == ["semantic", "jobs"] and len(parts) > 4 and parts[4] != str(row.id):
            raise forbidden()
    return actor


def resource_check(s: Session, p: Principal, key: UUID) -> None:
    if p.authentication_method != "job":
        return
    grant = s.get(JobExecutionGrant, p.execution_grant_id)
    if grant is None or str(key) not in grant.resources:
        raise forbidden()


def resolve_attempt(
    svc: Any, actor: Principal, kind: str, ontology: str, key: UUID, token: UUID
) -> Principal:
    from ontology_platform.security.service import PlatformAuthorizer

    if not isinstance(svc.authorizer, PlatformAuthorizer):
        return actor
    if actor.authentication_method != "job" and actor.principal_type != "service":
        raise forbidden()
    with svc.sessions.begin() as s, svc.authorizer.security_context(s, actor):
        p = context(s, svc.authorizer, actor, kind, key, token)
        if p.delegation_ontology != ontology:
            raise forbidden()
        return p


def claim_shared(svc: Any, actor: Principal, kind: str, ontology: str) -> tuple[UUID, UUID] | None:
    from sqlalchemy import or_

    model = IngestionRun if kind == "ingestion" else SemanticJob
    with svc.operation(actor, f"{kind}:claim", f"{ontology}/{kind}/jobs") as s:
        if actor.principal_type != "service" or actor.authentication_method not in {"oidc", "test"}:
            raise forbidden()
        svc.authorizer.require(actor, "worker:delegate", f"{actor.tenant_id}/{ontology}")
        svc.authorizer.require(actor, f"{kind}:execute", f"{actor.tenant_id}/{ontology}")
        now = clock(s)
        query = (
            select(model)
            .where(
                model.tenant_id == actor.tenant_id,
                model.ontology_id == ontology,
                or_(
                    model.status == "PENDING",
                    (model.status == "RUNNING") & (model.lease_until < now),
                ),
            )
            .order_by(model.created_at, model.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        while True:
            row = s.scalar(query)
            if row is None:
                return None
            p = actor.model_copy(
                update={"principal_id": row.principal_id, "actor_id": actor.principal_id}
            )
            try:
                p = context(s, svc.authorizer, actor, kind, row.id)
                svc.authorizer.require(p, f"{kind}:execute", f"{actor.tenant_id}/{ontology}")
            except ApplicationError:
                # Terminal quarantine, not silent omission or authority borrowed from the actor.
                row.status, row.last_error = "FAILED", "job_authorization_denied"
                row.completed_at, row.token, row.lease_until = now, None, None
                audit(s, p, row.id, p.execution_grant_id, "job:claim_denied")
                continue
            if row.attempts >= 3:
                row.status, row.last_error = "FAILED", "lease_exhausted"
                row.completed_at, row.token, row.lease_until = now, None, None
                audit(s, p, row.id, p.execution_grant_id, "job:lease_exhausted")
                continue
            row.status, row.token = "RUNNING", uuid4()
            row.attempts += 1
            row.lease_until = now + timedelta(seconds=60)
            if isinstance(row, IngestionRun):
                if row.started_at is None:
                    row.started_at = now
            else:
                row.history = row.history + [
                    {"event": "CLAIMED", "attempt": row.attempts, "at": now.isoformat()}
                ]
            audit(
                s,
                p.model_copy(update={"execution_token": row.token}),
                row.id,
                p.execution_grant_id,
                "job:claimed",
            )
            return row.id, row.token
    return None


def reject_attempt(
    svc: Any, p: Principal, ontology: str, key: UUID, token: UUID, code: str
) -> None:
    """Control-plane cleanup remains possible after the initiating user's authority is revoked.

    This path cannot read inputs or publish outputs; only the still-authorized actor and
    current fencing token may retire the failed attempt.
    """
    actor = worker(p) if p.authentication_method == "job" else p
    if p.job_kind not in {"ingestion", "semantic"}:
        raise forbidden()
    kind = p.job_kind
    model = IngestionRun if kind == "ingestion" else SemanticJob
    with svc.operation(actor, f"{kind}:claim", f"{ontology}/{kind}/jobs") as s:
        row = s.get(model, (actor.tenant_id, ontology, key), with_for_update=True)
        now = clock(s)
        if (
            row is None
            or row.token != token
            or row.status != "RUNNING"
            or row.lease_until is None
            or row.lease_until <= now
        ):
            return
        row.status, row.last_error, row.completed_at = "FAILED", code[:100], now
        row.token, row.lease_until = None, None
        audit(s, p, key, p.execution_grant_id, "job:execution_denied")


def check_commit(s: Session, auth: Any, p: Principal) -> None:
    """Expiry is rechecked at the final boundary, including a terminal state written here.

    The original job/grant locks and security revision are still held. Domain services own
    lease/fencing checks; terminal/retry changes in this transaction do not resurrect a grant.
    """
    snapshot = auth.snapshot.get()
    cached = snapshot.job_bindings.get(p.execution_grant_id) if snapshot else None
    if cached is None:
        raise forbidden()
    _, grant = cached
    auth.identity(s, p)
    auth.identity(s, worker(p))
    if grant.revoked_at is not None or grant.expires_at <= clock(s):
        raise forbidden()


def control_event(s: Session, auth: Any, p: Principal, kind: str, key: UUID, event: str) -> None:
    from ontology_platform.security.service import PlatformAuthorizer

    if isinstance(auth, PlatformAuthorizer):
        grant = find(s, p.tenant_id, kind, key)
        audit(s, p, key, grant.id if grant else None, event)
