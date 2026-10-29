"""Leased PostgreSQL ingestion runner with fenced, atomic step checkpoints."""

import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ontology_platform.actions.deadline import action_deadline
from ontology_platform.db.governance import missing
from ontology_platform.db.models import (
    IngestionDiagnostic,
    IngestionMapping,
    IngestionRun,
    IngestionStage,
)
from ontology_platform.errors import ApplicationError
from ontology_platform.ingestion.connectors import Extraction, encode, extract
from ontology_platform.ingestion.materialize import Materializer
from ontology_platform.ingestion.service import IngestionService
from ontology_platform.ingestion.transform import Proposed, transform, validate_mapping
from ontology_platform.metadata.storage import active_definition
from ontology_platform.security.interfaces import Principal


def clock(session: Session) -> datetime:
    value = session.scalar(select(func.clock_timestamp()))
    assert isinstance(value, datetime)
    return value


class IngestionWorker(IngestionService):
    def claim(self, p: Principal, ontology: str) -> tuple[UUID, UUID] | None:
        with self.operation(p, "ingestion:claim", f"{ontology}/ingestion/runs") as session:
            now = clock(session)
            run = session.scalar(
                select(IngestionRun)
                .where(
                    IngestionRun.tenant_id == p.tenant_id,
                    IngestionRun.ontology_id == ontology,
                    IngestionRun.principal_id == p.principal_id,
                    or_(
                        IngestionRun.status == "PENDING",
                        (IngestionRun.status == "RUNNING") & (IngestionRun.lease_until < now),
                    ),
                )
                .order_by(IngestionRun.created_at, IngestionRun.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if run is None:
                return None
            self.authorizer.require(
                p, "ingestion:execute", f"{p.tenant_id}/{ontology}/ingestion/runs/{run.id}"
            )
            if run.attempts >= 3:
                run.status, run.last_error = "FAILED", "lease_exhausted"
                run.completed_at = now
                run.token = None
                self.diag(session, run, None, "lease_exhausted", "job")
                return None
            run.status, run.token = "RUNNING", uuid4()
            run.attempts += 1
            run.lease_until = now + timedelta(seconds=60)
            if run.started_at is None:
                run.started_at = now
            return run.id, run.token

    @staticmethod
    def diag(
        session: Session,
        run: IngestionRun,
        number: int | None,
        code: str,
        category: str,
        mapping: tuple[str, int] | None = None,
    ) -> None:
        session.add(
            IngestionDiagnostic(
                tenant_id=run.tenant_id,
                ontology_id=run.ontology_id,
                id=uuid4(),
                run_id=run.id,
                row_number=number,
                mapping_id=mapping[0] if mapping else None,
                mapping_version=mapping[1] if mapping else None,
                code=code[:100],
                category=category,
            )
        )

    def fenced(
        self, session: Session, p: Principal, ontology: str, key: UUID, token: UUID
    ) -> IngestionRun:
        run = session.get(IngestionRun, (p.tenant_id, ontology, key), with_for_update=True)
        now = clock(session)
        if run is None:
            raise missing("Ingestion run")
        if (
            run.principal_id != p.principal_id
            or run.token != token
            or run.status != "RUNNING"
            or run.lease_until is None
            or run.lease_until <= now
        ):
            raise ApplicationError("lease_lost", "Worker no longer owns this ingestion run", 409)
        return run

    def renew(self, p: Principal, ontology: str, key: UUID, token: UUID) -> None:
        with self.operation(p, "ingestion:claim", f"{ontology}/ingestion/runs/{key}") as session:
            run = self.fenced(session, p, ontology, key, token)
            run.lease_until = clock(session) + timedelta(seconds=60)

    def _extract(
        self, p: Principal, ontology: str, key: UUID, token: UUID
    ) -> tuple[int, Extraction, list[Proposed]] | None:
        # Network/file/Polars work occurs without an operational transaction or ontology lock.
        with self.operation(p, "ingestion:execute", f"{ontology}/ingestion/runs/{key}") as session:
            self.ontology(session, p, ontology)
            run = self.fenced(session, p, ontology, key, token)
            if run.phase != "STAGING" or run.mapping_cursor >= len(run.plan):
                return None
            schema = active_definition(session, self.ontology(session, p, ontology))
            if schema.version != run.schema_version:
                raise ApplicationError("stale_schema", "Active schema changed", 409)
            ref = run.plan[run.mapping_cursor]
            assert isinstance(ref, dict)
            mapping = session.get(
                IngestionMapping, (p.tenant_id, ontology, ref["id"], ref["version"])
            )
            assert mapping is not None
            definition, _, binding = self.configuration(session, p, ontology, mapping)
            validate_mapping(schema, definition, binding)
            offset, size, checkpoint = run.row_cursor, run.batch_size, run.checkpoint
        extracted = extract(binding, offset, size)
        return checkpoint, extracted, transform(extracted.rows, schema, definition, binding)

    def _stage(
        self,
        session: Session,
        run: IngestionRun,
        data: tuple[int, Extraction, list[Proposed]] | None,
    ) -> None:
        if run.mapping_cursor >= len(run.plan):
            run.phase = "VALIDATING"
            return
        assert data is not None
        checkpoint, extracted, records = data
        if checkpoint != run.checkpoint:
            raise ApplicationError("checkpoint_changed", "Another step advanced this run", 409)
        observed = dict(run.observed)
        ref = run.plan[run.mapping_cursor]
        assert isinstance(ref, dict)
        mapping = session.get(
            IngestionMapping, (run.tenant_id, run.ontology_id, ref["id"], ref["version"])
        )
        assert mapping is not None
        key = f"{mapping.source_id}:{mapping.source_version}"
        if key in observed and observed[key] != extracted.fingerprint:
            raise ApplicationError("source_changed", "Source content changed during staging", 409)
        observed[key] = extracted.fingerprint
        run.observed = observed
        ref = run.plan[run.mapping_cursor]
        assert isinstance(ref, dict)
        mapping = session.get(
            IngestionMapping, (run.tenant_id, run.ontology_id, ref["id"], ref["version"])
        )
        assert mapping is not None
        from ontology_platform.ingestion.contracts import MappingInput

        definition = MappingInput.model_validate_json(mapping.definition_json)
        for proposal in records:
            run.staged += 1
            run.staged_bytes += len(encode([proposal.properties, proposal.relationships]))
            if run.staged > 10000 or run.staged_bytes > 16777216:
                raise ApplicationError("staging_limit", "Run exceeds staging limits", 422)
            if proposal.object_id and len(proposal.object_id.encode()) > 512:
                proposal.error = "identity_too_long"
            if proposal.source_key and len(proposal.source_key.encode()) > 512:
                proposal.error = "identity_too_long"
            session.add(
                IngestionStage(
                    tenant_id=run.tenant_id,
                    ontology_id=run.ontology_id,
                    run_id=run.id,
                    ordinal=run.staged,
                    mapping_id=definition.id,
                    mapping_version=definition.version,
                    row_number=proposal.number,
                    source_key=proposal.source_key,
                    object_type=definition.object_type,
                    object_id=proposal.object_id,
                    properties=proposal.properties if proposal.error is None else {},
                    relationships=proposal.relationships if proposal.error is None else [],
                    state="INVALID" if proposal.error else "STAGED",
                )
            )
            if proposal.error:
                run.rejected += 1
                self.diag(
                    session,
                    run,
                    proposal.number,
                    proposal.error,
                    "source" if proposal.error.startswith("source_") else "validation",
                    mapping=(definition.id, definition.version),
                )
        run.row_cursor += len(extracted.rows)
        if extracted.eof:
            run.mapping_cursor += 1
            run.row_cursor = 0
            if run.mapping_cursor >= len(run.plan):
                run.phase = "VALIDATING"

    def _validate(self, session: Session, run: IngestionRun) -> None:
        rows = list(
            session.scalars(
                select(IngestionStage)
                .where(
                    IngestionStage.tenant_id == run.tenant_id,
                    IngestionStage.ontology_id == run.ontology_id,
                    IngestionStage.run_id == run.id,
                )
                .order_by(IngestionStage.ordinal)
            )
        )
        source_counts = Counter(
            (r.mapping_id, r.source_key, r.object_type) for r in rows if r.state == "STAGED"
        )
        object_counts = Counter((r.object_type, r.object_id) for r in rows if r.state == "STAGED")
        for row in rows:
            if row.state == "STAGED" and (
                source_counts[(row.mapping_id, row.source_key, row.object_type)] > 1
                or object_counts[(row.object_type, row.object_id)] > 1
            ):
                row.state = "INVALID"
                run.rejected += 1
                self.diag(
                    session,
                    run,
                    row.row_number,
                    "duplicate_identity",
                    "validation",
                    mapping=(row.mapping_id, row.mapping_version),
                )
        invalid = [r for r in rows if r.state == "INVALID"]
        if run.policy == "reject_run" and (invalid or run.staged > 100):
            run.status = "FAILED"
            run.last_error = "invalid_records" if invalid else "atomic_run_too_large"
            run.completed_at = clock(session)
            run.token = None
            return
        if run.policy == "reject_batch":
            groups = {(r.ordinal - 1) // run.batch_size for r in invalid}
            for row in rows:
                if row.state == "STAGED" and (row.ordinal - 1) // run.batch_size in groups:
                    row.state = "REJECTED"
                    run.rejected += 1
                    self.diag(
                        session,
                        run,
                        row.row_number,
                        "batch_rejected",
                        "validation",
                        mapping=(row.mapping_id, row.mapping_version),
                    )
        run.phase = "OBJECTS"

    def _apply(self, session: Session, p: Principal, run: IngestionRun) -> None:
        materializer = Materializer(self, session, p, run.ontology_id)
        state = "STAGED" if run.phase == "OBJECTS" else "OBJECT_DONE"
        rows = list(
            session.scalars(
                select(IngestionStage)
                .where(
                    IngestionStage.tenant_id == run.tenant_id,
                    IngestionStage.ontology_id == run.ontology_id,
                    IngestionStage.run_id == run.id,
                    IngestionStage.state == state,
                )
                .order_by(IngestionStage.ordinal)
                .limit(100 if run.policy == "reject_run" else run.batch_size)
            )
        )
        if not rows:
            if run.phase == "OBJECTS":
                run.phase = "LINKS"
            else:
                run.phase = "DONE"
                run.status = "COMPLETED"
                run.completed_at = clock(session)
                run.token = None
            return

        def apply(row: IngestionStage) -> None:
            if run.phase == "OBJECTS":
                created, updated, conflict = materializer.objects_for(row)
                if conflict:
                    if run.policy != "quarantine":
                        raise ApplicationError(
                            "reconciliation_conflict", "Governed edit requires resolution", 409
                        )
                    row.state = "REJECTED"
                    run.rejected += 1
                    self.diag(
                        session,
                        run,
                        row.row_number,
                        "reconciliation_conflict",
                        "reconciliation",
                        mapping=(row.mapping_id, row.mapping_version),
                    )
                    return
                run.created += int(created)
                run.updated += int(updated)
                run.processed += 1
                row.state = "OBJECT_DONE"
            else:
                link_count, conflict = materializer.links_for(row)
                run.links_created += link_count
                row.state = "DONE"
                if conflict:
                    self.diag(
                        session,
                        run,
                        row.row_number,
                        "relationship_edit_conflict",
                        "reconciliation",
                        mapping=(row.mapping_id, row.mapping_version),
                    )

        if run.policy == "reject_run":
            # Bounded whole-run mode: objects and links commit in this one transaction.
            for row in rows:
                apply(row)
            run.phase = "LINKS"
            for row in rows:
                apply(row)
            run.phase = "DONE"
            run.status = "COMPLETED"
            run.completed_at = clock(session)
            run.token = None
        elif run.policy == "reject_batch":
            try:
                with session.begin_nested():
                    for row in rows:
                        apply(row)
                    session.flush()
            except ApplicationError as exc:
                if exc.status_code in {401, 403, 503}:
                    raise
                for row in rows:
                    row.state = "LINK_REJECTED" if run.phase == "LINKS" else "REJECTED"
                    run.rejected += 1
                    self.diag(
                        session,
                        run,
                        row.row_number,
                        exc.code,
                        "relationship" if run.phase == "LINKS" else "materialization",
                        mapping=(row.mapping_id, row.mapping_version),
                    )
        else:
            for row in rows:
                try:
                    with session.begin_nested():
                        apply(row)
                        session.flush()
                except ApplicationError as exc:
                    if exc.status_code in {401, 403, 503}:
                        raise
                    row.state = "LINK_REJECTED" if run.phase == "LINKS" else "REJECTED"
                    run.rejected += 1
                    self.diag(
                        session,
                        run,
                        row.row_number,
                        exc.code,
                        "relationship" if run.phase == "LINKS" else "materialization",
                        mapping=(row.mapping_id, row.mapping_version),
                    )

    def step(
        self,
        p: Principal,
        ontology: str,
        key: UUID,
        token: UUID,
        *,
        before_commit: Callable[[], None] | None = None,
    ) -> bool:
        data = self._extract(p, ontology, key, token)
        started = time.monotonic()
        with self.operation(p, "ingestion:execute", f"{ontology}/ingestion/runs/{key}") as session:
            with action_deadline(
                session,
                started + 15,
                code="ingestion_timeout",
                message="Batch exceeded its 15 second SQL budget",
            ):
                schema = active_definition(session, self.ontology(session, p, ontology, write=True))
                run = self.fenced(session, p, ontology, key, token)
                if schema.version != run.schema_version:
                    raise ApplicationError(
                        "stale_schema", "Active schema changed; submit a new run", 409
                    )
                if run.phase == "STAGING":
                    self._stage(session, run, data)
                elif run.phase == "VALIDATING":
                    self._validate(session, run)
                else:
                    self._apply(session, p, run)
                run.checkpoint += 1
                session.flush()
                if before_commit:
                    before_commit()
                now = clock(session)
                if run.lease_until is None or run.lease_until <= now:
                    raise ApplicationError("lease_lost", "Lease expired before batch commit", 409)
                if run.status == "RUNNING":
                    run.lease_until = now + timedelta(seconds=60)
                return run.status == "RUNNING"

    def fail(
        self,
        p: Principal,
        ontology: str,
        key: UUID,
        token: UUID,
        code: str,
        *,
        retryable: bool = False,
    ) -> None:
        with self.operation(p, "ingestion:execute", f"{ontology}/ingestion/runs/{key}") as session:
            run = session.get(IngestionRun, (p.tenant_id, ontology, key), with_for_update=True)
            if run is None or run.token != token or run.status != "RUNNING":
                return
            run.status = "PENDING" if retryable and run.attempts < 3 else "FAILED"
            run.last_error = code[:100]
            run.token = None
            run.lease_until = None
            if run.status == "FAILED":
                run.completed_at = clock(session)
            self.diag(session, run, None, code, "source" if code.startswith("source_") else "job")

    def run_one(self, p: Principal, ontology: str, max_steps: int = 40000) -> UUID | None:
        if not 1 <= max_steps <= 40000:
            raise ApplicationError("invalid_worker_limit", "Worker step limit is 1–40000", 422)
        claimed = self.claim(p, ontology)
        if claimed is None:
            return None
        key, token = claimed
        try:
            for _ in range(max_steps):
                if not self.step(p, ontology, key, token):
                    break
            else:
                self.fail(p, ontology, key, token, "step_limit", retryable=True)
        except ApplicationError as exc:
            if exc.code not in {"lease_lost", "checkpoint_changed"}:
                self.fail(p, ontology, key, token, exc.code, retryable=exc.status_code == 503)
        except (SQLAlchemyError, OSError, ValueError):
            self.fail(p, ontology, key, token, "worker_error", retryable=True)
        return key
