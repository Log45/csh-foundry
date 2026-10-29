"""Tenant-owned immutable configuration, job submission, status and diagnostics."""

import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.db.governance import GovernedService, missing
from ontology_platform.db.models import (
    IngestionDiagnostic,
    IngestionMapping,
    IngestionRun,
    IngestionSource,
)
from ontology_platform.errors import ApplicationError
from ontology_platform.ingestion.catalog import Binding, SourceCatalog
from ontology_platform.ingestion.contracts import (
    DiagnosticView,
    MappingInput,
    RunInput,
    RunView,
    SnapshotView,
    SourceInput,
)
from ontology_platform.ingestion.transform import validate_mapping
from ontology_platform.metadata.storage import active_definition
from ontology_platform.security.interfaces import Authorizer, Principal


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def origin(source: SourceInput) -> str:
    return digest([source.id, source.identity_namespace])


def registration_digest(binding: Binding) -> str:
    from sqlalchemy.engine import make_url

    definition = binding.model_dump(mode="json")
    if binding.url:
        definition["url"] = (
            make_url(binding.url.get_secret_value())
            .set(password=None)
            .render_as_string(hide_password=True)
        )
    return digest(definition)


class IngestionService(GovernedService):
    def __init__(
        self,
        sessions: sessionmaker[Session],
        authorizer: Authorizer,
        catalog: SourceCatalog,
        *,
        session: Session | None = None,
    ):
        super().__init__(sessions, authorizer, session=session)
        self.catalog = catalog

    def registered_binding(self, p: Principal, ontology: str, key: str) -> Binding:
        self.authorizer.require(
            p, "source:use_binding", f"{p.tenant_id}/{ontology}/source-bindings/{key}"
        )
        return self.catalog.get(p.tenant_id, key)

    def readable_source(self, p: Principal, ontology: str, row: IngestionSource) -> SnapshotView:
        self.authorizer.require(p, "source:read", f"{p.tenant_id}/{ontology}/sources/{row.id}")
        return self.snapshot(row)

    def readable_run(self, p: Principal, ontology: str, row: IngestionRun) -> RunView:
        self.authorizer.require(
            p, "ingestion:history", f"{p.tenant_id}/{ontology}/ingestion/runs/{row.id}"
        )
        return RunView.model_validate(row)

    @staticmethod
    def snapshot(row: IngestionSource | IngestionMapping) -> SnapshotView:
        return SnapshotView(
            tenant_id=row.tenant_id,
            ontology_id=row.ontology_id,
            kind=row.kind if isinstance(row, IngestionSource) else None,
            id=row.id,
            version=row.version,
            definition=json.loads(row.definition_json),
            created_by=row.created_by,
            created_at=row.created_at,
        )

    def source(
        self, session: Session, p: Principal, ontology: str, key: str, version: int
    ) -> IngestionSource:
        self.authorizer.require(p, "source:read", f"{p.tenant_id}/{ontology}/sources/{key}")
        row = session.get(IngestionSource, (p.tenant_id, ontology, key, version))
        if row is None:
            raise missing("Source version")
        return row

    def configuration(
        self, session: Session, p: Principal, ontology: str, mapping: IngestionMapping
    ) -> tuple[MappingInput, SourceInput, Binding]:
        if mapping.tenant_id != p.tenant_id or mapping.ontology_id != ontology:
            raise ApplicationError(
                "forbidden", "Mapping belongs to another tenant or ontology", 403
            )
        self.authorizer.require(
            p, "mapping:read", f"{p.tenant_id}/{ontology}/mappings/{mapping.id}"
        )
        source = self.source(session, p, ontology, mapping.source_id, mapping.source_version)
        request = SourceInput.model_validate_json(source.definition_json)
        binding = self.registered_binding(p, ontology, request.binding)
        if registration_digest(binding) != source.binding_revision or binding.kind != source.kind:
            raise ApplicationError(
                "registration_changed",
                "Source registration changed; publish a new source version",
                409,
            )
        return MappingInput.model_validate_json(mapping.definition_json), request, binding

    def create_source(self, p: Principal, ontology: str, request: SourceInput) -> SnapshotView:
        with self.operation(p, "source:create", f"{ontology}/sources/{request.id}") as session:
            self.ontology(session, p, ontology, write=True)
            self.authorizer.require(
                p, "source:publish", f"{p.tenant_id}/{ontology}/sources/{request.id}"
            )
            binding = self.registered_binding(p, ontology, request.binding)
            previous = session.scalar(
                select(IngestionSource)
                .where(
                    IngestionSource.tenant_id == p.tenant_id,
                    IngestionSource.ontology_id == ontology,
                    IngestionSource.id == request.id,
                )
                .order_by(IngestionSource.version.desc())
                .limit(1)
            )
            if (
                previous
                and SourceInput.model_validate_json(previous.definition_json).identity_namespace
                != request.identity_namespace
            ):
                raise ApplicationError(
                    "identity_namespace_immutable", "Source identity namespace cannot change", 409
                )
            row = IngestionSource(
                tenant_id=p.tenant_id,
                ontology_id=ontology,
                id=request.id,
                version=request.version,
                kind=binding.kind,
                definition_json=request.model_dump_json(),
                binding_revision=registration_digest(binding),
                created_by=p.principal_id,
            )
            session.add(row)
            session.flush()
            return self.snapshot(row)

    def sources(
        self, p: Principal, ontology: str, limit: int = 50, offset: int = 0
    ) -> list[SnapshotView]:
        self.page(limit, offset)
        with self.operation(p, "source:read", f"{ontology}/sources") as session:
            self.ontology(session, p, ontology)
            return [
                self.readable_source(p, ontology, r)
                for r in session.scalars(
                    select(IngestionSource)
                    .where(
                        IngestionSource.tenant_id == p.tenant_id,
                        IngestionSource.ontology_id == ontology,
                    )
                    .order_by(IngestionSource.id, IngestionSource.version)
                    .offset(offset)
                    .limit(limit)
                )
            ]

    def get_source(self, p: Principal, ontology: str, key: str, version: int) -> SnapshotView:
        with self.operation(p, "source:read", f"{ontology}/sources/{key}") as session:
            return self.snapshot(self.source(session, p, ontology, key, version))

    def create_mapping(self, p: Principal, ontology: str, request: MappingInput) -> SnapshotView:
        with self.operation(p, "mapping:create", f"{ontology}/mappings/{request.id}") as session:
            schema = active_definition(session, self.ontology(session, p, ontology, write=True))
            source = self.source(session, p, ontology, request.source_id, request.source_version)
            config = SourceInput.model_validate_json(source.definition_json)
            validate_mapping(schema, request, self.registered_binding(p, ontology, config.binding))
            self.authorizer.require(
                p, "mapping:publish", f"{p.tenant_id}/{ontology}/mappings/{request.id}"
            )
            row = IngestionMapping(
                tenant_id=p.tenant_id,
                ontology_id=ontology,
                id=request.id,
                version=request.version,
                source_id=request.source_id,
                source_version=request.source_version,
                schema_version=request.schema_version,
                definition_json=request.model_dump_json(),
                created_by=p.principal_id,
            )
            session.add(row)
            session.flush()
            return self.snapshot(row)

    def submit(self, p: Principal, ontology: str, request: RunInput) -> RunView:
        with self.operation(p, "ingestion:execute", f"{ontology}/ingestion/runs") as session:
            schema = active_definition(session, self.ontology(session, p, ontology, write=True))
            plan = [
                r.model_dump(mode="json")
                for r in sorted(request.mappings, key=lambda r: (r.id, r.version))
            ]
            fingerprint = digest([plan, request.batch_size, request.validation_policy])
            existing = session.scalar(
                select(IngestionRun).where(
                    IngestionRun.tenant_id == p.tenant_id,
                    IngestionRun.ontology_id == ontology,
                    IngestionRun.principal_id == p.principal_id,
                    IngestionRun.key_hash == digest(request.idempotency_key),
                )
            )
            if existing:
                if existing.request_hash != fingerprint:
                    raise ApplicationError(
                        "ingestion_key_conflict", "Run key belongs to a different request", 409
                    )
                self.authorizer.require(
                    p, "ingestion:history", f"{p.tenant_id}/{ontology}/ingestion/runs/{existing.id}"
                )
                return RunView.model_validate(existing)
            for ref in request.mappings:
                mapping = session.get(
                    IngestionMapping, (p.tenant_id, ontology, ref.id, ref.version)
                )
                if mapping is None:
                    raise missing("Mapping version")
                definition, _, binding = self.configuration(session, p, ontology, mapping)
                validate_mapping(schema, definition, binding)
            row = IngestionRun(
                tenant_id=p.tenant_id,
                ontology_id=ontology,
                id=uuid4(),
                schema_version=schema.version,
                principal_id=p.principal_id,
                plan=plan,
                policy=request.validation_policy,
                batch_size=request.batch_size,
                key_hash=digest(request.idempotency_key),
                request_hash=fingerprint,
            )
            session.add(row)
            session.flush()
            return RunView.model_validate(row)

    @staticmethod
    def page(limit: int, offset: int) -> None:
        if not 1 <= limit <= 100 or not 0 <= offset <= 10000:
            raise ApplicationError("invalid_page", "Invalid ingestion page", 422)

    def get(self, p: Principal, ontology: str, key: UUID) -> RunView:
        with self.operation(p, "ingestion:history", f"{ontology}/ingestion/runs/{key}") as session:
            row = session.get(IngestionRun, (p.tenant_id, ontology, key))
            if row is None:
                raise missing("Ingestion run")
            return RunView.model_validate(row)

    def runs(self, p: Principal, ontology: str, limit: int = 50, offset: int = 0) -> list[RunView]:
        self.page(limit, offset)
        with self.operation(p, "ingestion:history", f"{ontology}/ingestion/runs") as session:
            return [
                self.readable_run(p, ontology, r)
                for r in session.scalars(
                    select(IngestionRun)
                    .where(
                        IngestionRun.tenant_id == p.tenant_id, IngestionRun.ontology_id == ontology
                    )
                    .order_by(IngestionRun.created_at.desc(), IngestionRun.id)
                    .offset(offset)
                    .limit(limit)
                )
            ]

    def diagnostics(
        self, p: Principal, ontology: str, key: UUID, limit: int = 50, offset: int = 0
    ) -> list[DiagnosticView]:
        self.page(limit, offset)
        with self.operation(
            p, "ingestion:diagnostics", f"{ontology}/ingestion/runs/{key}"
        ) as session:
            if session.get(IngestionRun, (p.tenant_id, ontology, key)) is None:
                raise missing("Ingestion run")
            return [
                DiagnosticView.model_validate(r)
                for r in session.scalars(
                    select(IngestionDiagnostic)
                    .where(
                        IngestionDiagnostic.tenant_id == p.tenant_id,
                        IngestionDiagnostic.ontology_id == ontology,
                        IngestionDiagnostic.run_id == key,
                    )
                    .order_by(IngestionDiagnostic.created_at, IngestionDiagnostic.id)
                    .offset(offset)
                    .limit(limit)
                )
            ]

    def cancel(self, p: Principal, ontology: str, key: UUID) -> RunView:
        with self.operation(p, "ingestion:cancel", f"{ontology}/ingestion/runs/{key}") as session:
            row = session.get(IngestionRun, (p.tenant_id, ontology, key), with_for_update=True)
            if row is None:
                raise missing("Ingestion run")
            if row.status not in {"COMPLETED", "FAILED", "CANCELLED"}:
                row.cancel_requested = True
                row.status = "CANCELLED"
                row.completed_at = session.scalar(select(func.clock_timestamp()))
                row.token = None
            session.flush()
            return RunView.model_validate(row)

    def cleanup(self, p: Principal, ontology: str, days: int = 7, limit: int = 100) -> int:
        """Explicit bounded retention cleanup; immutable run/config history is retained."""
        from datetime import timedelta

        from sqlalchemy import delete

        from ontology_platform.db.models import IngestionStage

        if not 7 <= days <= 3650 or not 1 <= limit <= 100:
            raise ApplicationError(
                "invalid_retention", "Retention must be 7–3650 days; limit 1–100", 422
            )
        with self.operation(p, "ingestion:cleanup", f"{ontology}/ingestion/runs") as session:
            now = session.scalar(select(func.clock_timestamp()))
            assert now is not None
            runs = list(
                session.scalars(
                    select(IngestionRun)
                    .where(
                        IngestionRun.tenant_id == p.tenant_id,
                        IngestionRun.ontology_id == ontology,
                        IngestionRun.status.in_(["COMPLETED", "FAILED", "CANCELLED"]),
                        IngestionRun.completed_at < now - timedelta(days=days),
                        IngestionRun.staging_purged_at.is_(None),
                    )
                    .order_by(IngestionRun.completed_at)
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            )
            for run in runs:
                for model in (IngestionStage, IngestionDiagnostic):
                    session.execute(
                        delete(model).where(
                            model.tenant_id == p.tenant_id,
                            model.ontology_id == ontology,
                            model.run_id == run.id,
                        )
                    )
                run.staging_purged_at = now
            return len(runs)
