"""Durable PostgreSQL leasing; artifact transfers and child execution hold no tenant lock."""

import hashlib
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ontology_platform.artifacts.storage import Failure, StorageError
from ontology_platform.db.models import ArtifactVersion, ExecutionInput, ExecutionJob
from ontology_platform.db.session import clock
from ontology_platform.errors import ApplicationError
from ontology_platform.execution.config import ExecutionSettings
from ontology_platform.execution.isolation import isolated
from ontology_platform.pipelines.service import PipelineService
from ontology_platform.security import job_grants
from ontology_platform.security.interfaces import Principal
from ontology_platform.security.service import PlatformAuthorizer

ACTIVE = ["ADMITTED", "RUNNING", "CANCELLING"]


class ExecutionWorker:
    def __init__(self, service: PipelineService, actor: Principal | None = None):
        self.service = service
        self.sessions = service.sessions
        self.settings = ExecutionSettings()
        self.actor = actor
        if isinstance(service.authorizer, PlatformAuthorizer) and (
            actor is None
            or actor.principal_type != "service"
            or actor.authentication_method not in {"oidc", "test"}
        ):
            raise ApplicationError(
                "worker_identity_required", "Verified service identity required", 403
            )

    @contextmanager
    def control_scope(self) -> Iterator[Session]:
        if isinstance(self.service.authorizer, PlatformAuthorizer):
            assert self.actor is not None
            with self.service.scope(self.actor, "execution:claim") as s:
                yield s
        else:
            with self.sessions.begin() as s:
                yield s

    def principal(self, s: Session, job: ExecutionJob, token: UUID | None = None) -> Principal:
        if isinstance(self.service.authorizer, PlatformAuthorizer):
            assert self.actor is not None
            return job_grants.context(
                s, self.service.authorizer, self.actor, "execution", job.id, token
            )
        return Principal.model_validate(job.principal)

    def eligible(self, s: Session, job: ExecutionJob) -> None:
        if not isinstance(self.service.authorizer, PlatformAuthorizer):
            return
        assert self.actor is not None
        grant = job_grants.find(s, job.tenant_id, "execution", job.id)
        if grant is None:
            return  # Legacy quarantine remains explicit in the grant check below.
        try:
            for project in grant.projects:
                self.service.project(s, self.actor, UUID(project), write=True)
            for resource in grant.resources:
                if resource.startswith("scope:"):
                    continue
                from ontology_platform.db.models import Resource

                if s.get(Resource, (job.tenant_id, UUID(resource))) is not None:
                    self.service.resource(s, self.actor, UUID(resource))
        except ApplicationError as exc:
            if exc.status_code not in {403, 404}:
                raise
            raise ApplicationError(
                "worker_ineligible", "Worker resource scope does not cover job", 403
            ) from exc

    def check_authority(
        self, s: Session, job: ExecutionJob, token: UUID | None = None
    ) -> Principal:
        p = self.principal(s, job, token)
        if isinstance(self.service.authorizer, PlatformAuthorizer):
            self.service.authorizer.require(p, "project:read", f"{p.tenant_id}/projects")
            if job.kind == "FUNCTION":
                from ontology_platform.functions.service import FunctionService
                from ontology_platform.functions.worker import authorize

                root = self.service
                authorize(
                    FunctionService(root.sessions, root.authorizer, root.settings, root.store),
                    s,
                    p,
                    job,
                )
            elif job.kind == "MATERIALIZATION":
                from ontology_platform.mappings.worker import authorize as authorize_mapping

                authorize_mapping(self, s, p, job)
            else:
                self.authorize(s, p, job)
        return p

    def claim(self) -> tuple[UUID, UUID, UUID] | None:
        with self.control_scope() as s:
            if self.actor is not None and isinstance(self.service.authorizer, PlatformAuthorizer):
                self.service.authorizer.require(
                    self.actor, "worker:delegate", f"{self.actor.tenant_id}/projects"
                )
            s.execute(text("SELECT pg_advisory_xact_lock(14214001)"))
            now = clock(s)
            expired = s.scalars(
                select(ExecutionJob)
                .where(
                    ExecutionJob.state.in_(ACTIVE),
                    ExecutionJob.lease_until < now,
                    *([ExecutionJob.tenant_id == self.actor.tenant_id] if self.actor else []),
                )
                .with_for_update(skip_locked=True)
                .limit(100)
            )
            for row in expired:
                row.token, row.lease_until = None, None
                if row.state == "CANCELLING":
                    row.state, row.completed_at = "CANCELLED", now
                elif row.attempts >= self.settings.attempts:
                    row.state, row.completed_at, row.error = "FAILED", now, "lease_expired"
                else:
                    row.state = "QUEUED"
            s.flush()
            active = list(s.scalars(select(ExecutionJob).where(ExecutionJob.state.in_(ACTIVE))))
            if len(active) >= self.settings.concurrent_jobs:
                return None
            candidates = s.scalars(
                select(ExecutionJob)
                .where(
                    ExecutionJob.state == "QUEUED",
                    *([ExecutionJob.tenant_id == self.actor.tenant_id] if self.actor else []),
                )
                .order_by(ExecutionJob.created_at, ExecutionJob.id)
                .with_for_update(skip_locked=True)
                .limit(self.settings.queue_jobs)
            )
            for row in candidates:
                if row.kind == "FUNCTION":
                    from ontology_platform.functions.contracts import GSettings

                    if sum(j.kind == "FUNCTION" for j in active) >= GSettings().function_jobs:
                        continue
                if sum(j.tenant_id == row.tenant_id for j in active) >= self.settings.tenant_jobs:
                    continue
                if (
                    sum(
                        j.tenant_id == row.tenant_id and j.project_id == row.project_id
                        for j in active
                    )
                    >= self.settings.project_jobs
                ):
                    continue
                try:
                    self.eligible(s, row)
                    p = self.check_authority(s, row)
                except ApplicationError as exc:
                    if exc.code == "worker_ineligible":
                        assert self.actor is not None
                        grant = job_grants.find(s, row.tenant_id, "execution", row.id)
                        denied = self.actor.model_copy(
                            update={
                                "principal_id": grant.principal_id if grant else "unresolved",
                                "actor_id": self.actor.principal_id,
                            }
                        )
                        job_grants.audit(
                            s,
                            denied,
                            row.id,
                            grant.id if grant else None,
                            "job:worker_eligibility_denied",
                        )
                        continue
                    row.state, row.completed_at, row.error = (
                        "FAILED",
                        now,
                        "job_authorization_denied",
                    )
                    if self.actor:
                        denied_actor = self.actor.model_copy(
                            update={
                                "principal_id": str(
                                    row.principal.get("principal_id", "unresolved")
                                ),
                                "actor_id": self.actor.principal_id,
                            }
                        )
                        grant = job_grants.find(s, row.tenant_id, "execution", row.id)
                        job_grants.audit(
                            s, denied_actor, row.id, grant.id if grant else None, "job:claim_denied"
                        )
                    continue
                row.state, row.token = "ADMITTED", uuid4()
                row.admitted_at, row.heartbeat_at = now, now
                row.started_at = None
                row.attempts += 1
                row.lease_until = now + timedelta(seconds=self.settings.lease_seconds)
                job_grants.audit(
                    s,
                    p.model_copy(update={"execution_token": row.token}),
                    row.id,
                    p.execution_grant_id,
                    "job:claimed",
                )
                return row.tenant_id, row.id, row.token
            return None

    def fenced(self, s: Session, tenant: UUID, key: UUID, token: UUID) -> ExecutionJob:
        if self.actor is not None and tenant != self.actor.tenant_id:
            raise ApplicationError("forbidden", "Worker tenant mismatch", 403)
        row = s.get(ExecutionJob, (tenant, key), with_for_update=True)
        if (
            row is None
            or row.token != token
            or row.state not in {"ADMITTED", "RUNNING"}
            or row.lease_until is None
            or row.lease_until <= clock(s)
        ):
            raise ApplicationError("lease_lost", "Worker lease lost", 409)
        if (
            row.started_at is not None
            and (clock(s) - row.started_at).total_seconds()
            > ExecutionSettings.model_validate(row.limits).wall_seconds
        ):
            raise ApplicationError("execution_limit", "Execution deadline exceeded", 409)
        self.check_authority(s, row, token)
        return row

    def heartbeat(self, tenant: UUID, key: UUID, token: UUID) -> bool:
        if self.actor is not None and tenant != self.actor.tenant_id:
            raise ApplicationError("forbidden", "Worker tenant mismatch", 403)
        with self.control_scope() as s:
            try:
                row = self.fenced(s, tenant, key, token)
            except ApplicationError as exc:
                if exc.code == "execution_limit" or exc.status_code in {401, 403, 404}:
                    expired = s.get(ExecutionJob, (tenant, key), with_for_update=True)
                    assert expired is not None
                    expired.state, expired.completed_at, expired.error = (
                        "FAILED",
                        clock(s),
                        "execution_limit"
                        if exc.code == "execution_limit"
                        else "job_authorization_denied",
                    )
                    expired.token, expired.lease_until = None, None
                    if isinstance(self.service.authorizer, PlatformAuthorizer):
                        denied = self.principal(s, expired, token)
                        job_grants.audit(
                            s, denied, key, denied.execution_grant_id, "job:execution_denied"
                        )
                return False
            row.heartbeat_at = clock(s)
            row.lease_until = row.heartbeat_at + timedelta(seconds=self.settings.lease_seconds)
            return True

    def authorize(self, s: Session, p: Principal, job: ExecutionJob) -> list[ArtifactVersion]:
        svc, datasets = self.service, self.service.datasets()
        resource = svc.resource(s, p, job.resource_id)
        if job.kind == "VALIDATION":
            datasets.artifact(s, p, resource.id, True)
            assert job.validation_version_id is not None
            return [datasets.version(s, p, resource.id, job.validation_version_id)]
        assert job.definition_id is not None
        svc.artifact(s, p, job.resource_id, True)
        svc.definition(s, p, resource.id, job.definition_id)
        if job.request.get("format_version") == 2:
            from ontology_platform.pipelines.dag import DAGDefinition
            from ontology_platform.pipelines.dag_service import validate_in

            spec = DAGDefinition.model_validate(
                svc.definition(s, p, resource.id, job.definition_id).specification
            )
            validate_in(svc, s, p, spec)
        else:
            assert job.output_dataset_id is not None
            datasets.artifact(s, p, job.output_dataset_id, True)
        versions = []
        for item in s.scalars(
            select(ExecutionInput)
            .where(ExecutionInput.tenant_id == p.tenant_id, ExecutionInput.job_id == job.id)
            .order_by(ExecutionInput.name)
        ):
            logical = datasets.record(s, p, item.dataset_id, item.version_id)
            physical = datasets.version(s, p, item.dataset_id, item.version_id)
            if (
                logical.state != "COMMITTED"
                or physical.state != "COMMITTED"
                or physical.checksum != item.checksum
            ):
                raise ApplicationError("invalid_input", "Input is not committed", 409)
            versions.append(physical)
        return versions

    def spool(
        self, physical: ArtifactVersion, path: Path, limits: ExecutionSettings, renew: Any
    ) -> None:
        svc = self.service.datasets()
        digest, size = hashlib.sha256(), 0
        if physical.size > min(limits.source_bytes, limits.temporary_bytes):
            raise ApplicationError("source_limit", "Source exceeds worker budget", 413)
        with path.open("wb") as file:
            for chunk in svc.storage().chunks(svc.key(physical)):
                size += len(chunk)
                if size > physical.size:
                    raise StorageError(Failure.INTEGRITY)
                digest.update(chunk)
                file.write(chunk)
                if size % (8 * 1024**2) < len(chunk) and not renew():
                    raise ApplicationError("lease_lost", "Worker lease lost", 409)
        if size != physical.size or digest.hexdigest() != physical.checksum:
            raise StorageError(Failure.INTEGRITY)

    def execute(self, tenant: UUID, key: UUID, token: UUID) -> None:
        svc, datasets = self.service, self.service.datasets()
        with self.control_scope() as s:
            job = self.fenced(s, tenant, key, token)
            p = self.principal(s, job, token)
            limits = ExecutionSettings.model_validate(job.limits)
            if p.authentication_method in {"oidc", "test"}:
                p = p.model_copy(
                    update={
                        "expires_at": datetime.now(UTC)
                        + timedelta(seconds=limits.wall_seconds + limits.lease_seconds + 300)
                    }
                )
        if job.kind == "PIPELINE" and job.request.get("format_version") == 2:
            from ontology_platform.pipelines.dag_worker import execute as execute_dag

            execute_dag(self, tenant, key, token, p, limits)
            return
        if job.kind == "FUNCTION":
            from ontology_platform.functions.worker import execute as execute_function

            execute_function(self, tenant, key, token, p, limits)
            return
        if job.kind == "MATERIALIZATION":
            from ontology_platform.mappings.worker import execute

            execute(self, tenant, key, token, p, limits)
            return
        with svc.scope(p) as s:
            job = self.fenced(s, tenant, key, token)
            versions = self.authorize(s, p, job)
            job.state = "RUNNING"
            job.started_at = clock(s)
            kind = job.kind
            if kind == "PIPELINE":
                from ontology_platform.pipelines.engine import PolarsEngine

                if job.request.get("engine_version") != PolarsEngine.version:
                    raise ApplicationError(
                        "engine_version", "Pinned execution engine unavailable", 503
                    )
            specification = None
            if kind == "PIPELINE":
                assert job.definition_id is not None
                specification = svc.definition(
                    s, p, job.resource_id, job.definition_id
                ).specification
            inputs = list(
                s.scalars(
                    select(ExecutionInput)
                    .where(ExecutionInput.tenant_id == tenant, ExecutionInput.job_id == key)
                    .order_by(ExecutionInput.name)
                )
            )
            # Detach only immutable metadata; no transaction remains open during I/O.
            for version in versions:
                if version in s:
                    s.expunge(version)

        def renew() -> bool:
            return self.heartbeat(tenant, key, token)

        with tempfile.TemporaryDirectory(prefix="foundry-execution-") as temporary:
            directory = Path(temporary)
            if sum(v.size for v in versions) > limits.temporary_bytes:
                raise ApplicationError("temporary_limit", "Inputs exceed temporary budget", 413)
            resolved = []
            for i, physical in enumerate(versions):
                path = directory / f"input-{i}"
                self.spool(physical, path, limits, renew)
                logical = datasets.dataset_metadata(p, physical.artifact_id, physical.id)
                resolved.append(
                    {
                        "path": str(path),
                        "format": logical.format,
                        "schema": logical.result.get("schema"),
                        "row_count": logical.result.get("row_count"),
                        "name": inputs[i].name if kind == "PIPELINE" else "source",
                    }
                )
            if kind == "VALIDATION":
                physical = versions[0]
                with svc.scope(p) as s:
                    job = self.fenced(s, tenant, key, token)
                    self.authorize(s, p, job)
                    row = datasets.version(s, p, physical.artifact_id, physical.id)
                    if row.state == "PENDING":
                        row.state, row.committed_at = "COMMITTED", clock(s)
                        s.flush()
            request = (
                resolved[0]
                if kind == "VALIDATION"
                else {"specification": specification, "inputs": resolved}
            )
            result = isolated(
                "validation" if kind == "VALIDATION" else "pipeline",
                request,
                directory,
                limits,
                renew,
            )
            if "error" in result:
                if kind == "VALIDATION" and result["error"] == "invalid_data_or_plan":
                    with svc.scope(p) as s:
                        job = self.fenced(s, tenant, key, token)
                        self.authorize(s, p, job)
                        logical_row = datasets.record(s, p, versions[0].artifact_id, versions[0].id)
                        if logical_row.state == "PENDING":
                            logical_row.state = "FAILED"
                            logical_row.result = result
                            logical_row.finalized_at = clock(s)
                        job.state, job.completed_at, job.error = (
                            "FAILED",
                            clock(s),
                            "invalid_data_or_plan",
                        )
                        job.metrics = result.get("metrics", {})
                        job.token, job.lease_until = None, None
                        svc.audit(s, p, "dataset_validation_failed", job.id)
                self.fail(
                    tenant, key, token, str(result["error"]), False, result.get("metrics", {})
                )
                return
            if kind == "VALIDATION":
                physical = versions[0]
                # Physical and logical publication is atomic after the streaming checksum above.
                with svc.scope(p) as s:
                    job = self.fenced(s, tenant, key, token)
                    self.authorize(s, p, job)
                    row = datasets.version(s, p, physical.artifact_id, physical.id)
                    if row.state == "PENDING":
                        row.state, row.committed_at = "COMMITTED", clock(s)
                        s.flush()
                    logical_row = datasets.record(s, p, physical.artifact_id, physical.id)
                    if logical_row.state == "PENDING":
                        logical_row.state, logical_row.result, logical_row.finalized_at = (
                            "COMMITTED",
                            result,
                            clock(s),
                        )
                    s.flush()
                    job.state, job.completed_at, job.metrics = (
                        "SUCCEEDED",
                        clock(s),
                        result.get("metrics", {}),
                    )
                    job.token, job.lease_until = None, None
                    svc.audit(s, p, "dataset_validation_committed", physical.id)
                return
            self.publish(p, key, token, directory, result)

    def publish(
        self, p: Principal, key: UUID, token: UUID, directory: Path, result: dict[str, Any]
    ) -> None:
        svc, datasets = self.service, self.service.datasets()
        with svc.scope(p) as s:
            job = self.fenced(s, p.tenant_id, key, token)
            self.authorize(s, p, job)
            assert job.output_dataset_id is not None
            if job.output_version_id is None:
                nested = datasets.__class__(
                    datasets.sessions, datasets.authorizer, datasets.settings, datasets.store
                )
                nested.transaction_session = s
                from ontology_platform.datasets.contracts import InitiateDataset

                output = nested.initiate_dataset(
                    p,
                    job.output_dataset_id,
                    InitiateDataset(
                        filename="pipeline-output.parquet",
                        format="parquet",
                        size=result["size"],
                        checksum=result["checksum"],
                        source="pipeline-run:" + str(key),
                    ),
                )
                job.output_version_id = output.id
                s.flush()
            physical = datasets.version(s, p, job.output_dataset_id, job.output_version_id)
            s.expunge(physical)
        if physical.size != result["size"] or physical.checksum != result["checksum"]:
            raise ApplicationError(
                "output_mismatch", "Recovered output does not match reservation", 409
            )
        obj, store = datasets.key(physical), datasets.storage()
        if not self.heartbeat(p.tenant_id, key, token):
            raise ApplicationError("lease_lost", "Worker lease lost", 409)
        if store.exists(obj):
            store.verify(obj, physical.size, physical.checksum)
        else:
            with (directory / "output.parquet").open("rb") as file:
                try:
                    store.put(obj, file, physical.size, physical.checksum)
                except StorageError as exc:
                    if exc.category != Failure.EXISTS:
                        raise
                    store.verify(obj, physical.size, physical.checksum)
        if not self.heartbeat(p.tenant_id, key, token):
            raise ApplicationError("lease_lost", "Worker lease lost", 409)
        with svc.scope(p) as s:
            job = self.fenced(s, p.tenant_id, key, token)
            self.authorize(s, p, job)
            s.execute(
                text("SELECT set_config('foundry.execution_token', :token, true)"),
                {"token": str(token)},
            )
            row = datasets.version(s, p, physical.artifact_id, physical.id)
            if row.state == "PENDING":
                row.state, row.committed_at = "COMMITTED", clock(s)
                s.flush()
            logical = datasets.record(s, p, row.artifact_id, row.id)
            if logical.state == "PENDING":
                logical.state, logical.result, logical.finalized_at = (
                    "COMMITTED",
                    result["dataset"],
                    clock(s),
                )
                s.flush()
            job.state, job.completed_at, job.metrics = (
                "SUCCEEDED",
                clock(s),
                result.get("metrics", {}),
            )
            job.token, job.lease_until = None, None
            svc.audit(s, p, "pipeline_run_succeeded", job.id)

    def fail(
        self,
        tenant: UUID,
        key: UUID,
        token: UUID,
        code: str,
        retryable: bool,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        if self.actor is not None and tenant != self.actor.tenant_id:
            raise ApplicationError("forbidden", "Worker tenant mismatch", 403)
        with self.control_scope() as s:
            row = s.get(ExecutionJob, (tenant, key), with_for_update=True)
            if row is None or row.token != token or row.state not in ACTIVE:
                return
            if row.lease_until is None or row.lease_until <= clock(s):
                return
            if row.state == "CANCELLING":
                row.state, row.completed_at = "CANCELLED", clock(s)
            elif retryable and row.attempts < self.settings.attempts:
                row.state = "QUEUED"
            else:
                row.state, row.completed_at = "FAILED", clock(s)
            row.error, row.metrics = code, dict(row.metrics) | (metrics or {})
            row.token, row.lease_until = None, None
            self.service.audit(
                s,
                self.principal(s, row).model_copy(update={"execution_token": token}),
                "execution_" + row.state.lower(),
                row.id,
                {"error": code, "attempt": row.attempts},
            )

    def run_one(self) -> UUID | None:
        from ontology_platform.pipelines.dag_worker import sweep

        try:
            sweep(self)
        except (ApplicationError, SQLAlchemyError):
            pass
        from ontology_platform.observability.index import tick

        try:
            with self.control_scope() as session:
                tick(self.sessions, self.actor.tenant_id if self.actor else None, session=session)
        except SQLAlchemyError:
            # Canonical execution remains available; pending generations expose index lag.
            pass
        claim = self.claim()
        if claim is None:
            return None
        tenant, key, token = claim
        stopped = threading.Event()

        def keepalive() -> None:
            while not stopped.wait(max(1, self.settings.lease_seconds / 3)):
                try:
                    if not self.heartbeat(tenant, key, token):
                        return
                except SQLAlchemyError:
                    return  # Lease expiry fences this attempt if the database stays unavailable.

        thread = threading.Thread(target=keepalive, daemon=True)
        thread.start()
        try:
            self.execute(tenant, key, token)
        except StorageError as exc:
            self.fail(tenant, key, token, exc.code, exc.category == Failure.TRANSIENT)
        except ApplicationError as exc:
            if exc.code != "lease_lost":
                self.fail(
                    tenant,
                    key,
                    token,
                    exc.code
                    if exc.code
                    in {
                        "execution_limit",
                        "temporary_limit",
                        "source_limit",
                        "engine_version",
                        "intermediate_limit",
                        "output_limit",
                        "output_serialization",
                        "invalid_data_or_plan",
                        "plan_integrity",
                        "manifest_limit",
                        "intermediate_integrity",
                        "input_unavailable",
                        "storage_disabled",
                        "output_unavailable",
                        "schema_mismatch",
                        "memory_limit",
                    }
                    else "authorization_or_contract",
                    False,
                )
            else:
                self.fail(tenant, key, token, "cancelled", False)
        except (SQLAlchemyError, OSError):
            self.fail(tenant, key, token, "infrastructure", True)
        except Exception:
            self.fail(tenant, key, token, "execution_failed", False)
        finally:
            stopped.set()
            thread.join(timeout=5)
            from ontology_platform.pipelines.dag_worker import cleanup

            try:
                cleanup(self, tenant, key, repeat=True)
            except (ApplicationError, SQLAlchemyError):
                pass  # Private orphan bytes can be swept safely on a later worker tick.
        return key
