"""Governed semantic artifacts and jobs; PostgreSQL operational facts are read-only here."""

import json
import time
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID, uuid4

from ontology_schema.models import OntologyDefinition, OperationalIdentity, RDFMapping
from rdflib import RDF, Graph, URIRef
from sqlalchemy import select
from sqlalchemy.orm import Session

from ontology_platform.actions.deadline import action_deadline
from ontology_platform.db.governance import GovernedService, missing
from ontology_platform.db.models import DerivedFact, SemanticApproval, SemanticArtifact, SemanticJob
from ontology_platform.errors import ApplicationError
from ontology_platform.ingestion.provenance import export_provenance
from ontology_platform.metadata.storage import definition_of, version_row
from ontology_platform.queries.compiler import QueryCompiler
from ontology_platform.queries.service import QueryService
from ontology_platform.security.interfaces import Principal
from ontology_platform.semantic.compiler import (
    compile_schema,
    digest,
    literal,
    parse,
    serialize,
    term,
)
from ontology_platform.semantic.contracts import (
    COMPILER_VERSION,
    MAX_BYTES,
    ApprovalEvent,
    ApprovalInput,
    ArtifactManifest,
    ArtifactView,
    CompileInput,
    Diagnostic,
    ExportInput,
    FactView,
    JobInput,
    JobView,
    Kind,
    NativeInput,
)
from ontology_platform.semantic.engine import ENGINE_COMMIT, ENGINE_VERSION


def encode(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


class SemanticService(GovernedService):
    def schema(
        self, session: Session, p: Principal, ontology: str, version: str, *, active: bool = False
    ) -> OntologyDefinition:
        self.authorizer.require(p, "schema:read", f"{p.tenant_id}/{ontology}/versions/{version}")
        root = self.ontology(session, p, ontology)
        row = version_row(session, root, version)
        if row.status != "PUBLISHED":
            raise ApplicationError(
                "unpublished_schema", "Semantic inputs require a published schema", 409
            )
        if active and root.active_version != version:
            raise ApplicationError(
                "stale_schema", "Operational export requires the active schema", 409
            )
        return definition_of(row)

    def store(
        self,
        session: Session,
        p: Principal,
        ontology: str,
        version: str,
        kind: Kind,
        content: bytes,
        *,
        inputs: dict[str, str] | None = None,
        provenance: dict[str, object] | None = None,
        diagnostics: list[Diagnostic] | None = None,
    ) -> SemanticArtifact:
        if len(content) > MAX_BYTES:
            raise ApplicationError("semantic_resource_limit", "Artifact exceeds 4 MiB", 422)
        output_hash = digest(content)
        fingerprint = digest(
            encode(
                [
                    version,
                    kind,
                    COMPILER_VERSION,
                    ENGINE_VERSION,
                    output_hash,
                    inputs or {},
                    provenance or {},
                ]
            ).encode()
        )
        existing = session.scalar(
            select(SemanticArtifact).where(
                SemanticArtifact.tenant_id == p.tenant_id,
                SemanticArtifact.ontology_id == ontology,
                SemanticArtifact.principal_id == p.principal_id,
                SemanticArtifact.fingerprint == fingerprint,
            )
        )
        if existing:
            return existing
        manifest = ArtifactManifest(
            id=uuid4(),
            tenant_id=p.tenant_id,
            ontology_id=ontology,
            schema_version=version,
            kind=kind,
            engine_version=ENGINE_VERSION,
            engine_commit=ENGINE_COMMIT,
            created_at=datetime.now(UTC),
            principal_id=p.principal_id,
            input_hashes=inputs or {},
            output_hash=output_hash,
            provenance=provenance or {},
            diagnostics=diagnostics or [],
        )
        row = SemanticArtifact(
            tenant_id=p.tenant_id,
            ontology_id=ontology,
            id=manifest.id,
            schema_version=version,
            principal_id=p.principal_id,
            kind=kind,
            content=content.decode(),
            output_hash=output_hash,
            fingerprint=fingerprint,
            manifest_json=manifest.model_dump_json(by_alias=True),
        )
        session.add(row)
        session.flush()
        return row

    def row(self, session: Session, p: Principal, ontology: str, key: UUID) -> SemanticArtifact:
        self.authorizer.require(
            p, "semantic:read", f"{p.tenant_id}/{ontology}/semantic/artifacts/{key}"
        )
        row = session.get(SemanticArtifact, (p.tenant_id, ontology, key))
        if row is None or row.principal_id != p.principal_id:
            raise missing("Artifact")
        self.schema(session, p, ontology, row.schema_version)
        if digest(row.content.encode()) != row.output_hash:
            raise ApplicationError("artifact_integrity", "Artifact integrity check failed", 409)
        manifest = ArtifactManifest.model_validate_json(row.manifest_json)
        if (
            manifest.id,
            manifest.output_hash,
            manifest.tenant_id,
            manifest.ontology_id,
            manifest.schema_version,
            manifest.principal_id,
            manifest.kind,
        ) != (
            row.id,
            row.output_hash,
            row.tenant_id,
            row.ontology_id,
            row.schema_version,
            row.principal_id,
            row.kind,
        ):
            raise ApplicationError("artifact_integrity", "Manifest integrity check failed", 409)
        return row

    def compile(self, p: Principal, ontology: str, body: CompileInput) -> list[UUID]:
        with self.operation(p, "semantic:compile", f"{ontology}/semantic") as session:
            schema = self.schema(session, p, ontology, body.schema_version)
            owl, shapes, diagnostics = compile_schema(schema)
            return [
                self.store(
                    session,
                    p,
                    ontology,
                    schema.version,
                    cast(Kind, kind),
                    content,
                    inputs={"canonical": digest(schema.canonical_json().encode())},
                    provenance={"origin": "canonical", "approval": "compiled_published_schema"},
                    diagnostics=diagnostics,
                ).id
                for kind, content in (("ontology", owl), ("shapes", shapes))
            ]

    def native(self, p: Principal, ontology: str, body: NativeInput) -> UUID:
        # Opaque reviewed semantic input; no translation, publication or activation of OWL imports.
        with self.operation(p, "semantic:publish", f"{ontology}/semantic") as session:
            self.schema(session, p, ontology, body.schema_version)
            parse(
                body.content.encode(), "invalid_shacl" if body.kind == "shapes" else "invalid_rdf"
            )
            return self.store(
                session,
                p,
                ontology,
                body.schema_version,
                body.kind,
                body.content.encode(),
                provenance={"origin": "approved_native", "approved_by": p.principal_id},
            ).id

    def snapshot(
        self, session: Session, p: Principal, ontology: str, body: ExportInput
    ) -> tuple[bytes, dict[str, object]]:
        schema = self.schema(session, p, ontology, body.schema_version, active=True)
        service = QueryService(self.sessions, self.authorizer, session=session)
        compiler = QueryCompiler(schema, p, self.authorizer)
        mapping = RDFMapping(namespace=schema.namespace)
        graph = Graph()
        selected: dict[str, list[str]] = {}
        revisions: dict[str, int] = {}
        policies: dict[str, object] = {}
        start = time.monotonic()

        def iri(kind: str, key: str) -> URIRef:
            return URIRef(
                mapping.individual_iri(
                    OperationalIdentity(
                        tenant_id=p.tenant_id,
                        ontology_id=ontology,
                        object_type_id=kind,
                        object_id=key,
                    )
                )
            )

        for query in body.selections:
            if query.traverse or query.cursor or query.offset or query.object_type in selected:
                raise ApplicationError(
                    "invalid_export",
                    "Use unique root types with no cursor, offset or traversal",
                    422,
                )
            policies[query.object_type] = compiler.grant(query.object_type).model_dump(
                mode="json", by_alias=True
            )
            page = service.query(p, ontology, query)
            selected[query.object_type] = []
            typed = next(t for t in schema.object_types if t.id == query.object_type)
            for obj in page.items:
                resource = f"{p.tenant_id}/{ontology}/objects/{typed.id}/{obj.object_id}"
                self.authorizer.require(p, "object:read", resource)
                selected[typed.id].append(obj.object_id)
                subject = iri(typed.id, obj.object_id)
                revisions[str(subject)] = obj.version
                graph.add((subject, RDF.type, term(schema.namespace, "class", typed.id)))
                for key, value in obj.properties.items():
                    self.authorizer.require(p, "property:read", resource + f"/properties/{key}")
                    if value is not None:
                        prop = next(item for item in typed.properties if item.id == key)
                        graph.add(
                            (
                                subject,
                                term(schema.namespace, "property", typed.id, key),
                                literal(prop, value),
                            )
                        )
            if sum(map(len, selected.values())) > 1000:
                raise ApplicationError(
                    "semantic_resource_limit", "Export exceeds 1000 objects", 422
                )
        edges = service.export_edges(p, ontology, body.links, selected)
        for link, source_type, source, target_type, target, _ in edges:
            graph.add(
                (
                    iri(source_type, source),
                    term(schema.namespace, "link", link),
                    iri(target_type, target),
                )
            )
            definition = next(t for t in schema.link_types if t.id == link)
            if definition.inverse_name:
                graph.add(
                    (
                        iri(target_type, target),
                        term(schema.namespace, "inverse-link", link),
                        iri(source_type, source),
                    )
                )
        if time.monotonic() - start > 10:
            raise ApplicationError("semantic_resource_limit", "Export exceeds ten seconds", 422)
        provenance: dict[str, object] = {
            "ingestion": export_provenance(session, self.authorizer, p, ontology, selected),
            "export": body.model_dump(mode="json", by_alias=True),
            "selected": selected,
            "policy_hash": digest(encode(policies).encode()),
            "revisions": revisions,
            "edge_boundary": digest(encode(edges).encode()),
            "namespace": schema.namespace,
            "iri_mapping_version": 1,
            "boundary": "bounded_query_under_shared_ontology_lock",
        }
        return serialize(graph), provenance

    def export(self, p: Principal, ontology: str, body: ExportInput) -> UUID:
        with self.operation(p, "semantic:export", f"{ontology}/semantic") as session:
            with action_deadline(
                session,
                time.monotonic() + 10,
                code="semantic_resource_limit",
                message="Export exceeds ten seconds",
            ):
                content, provenance = self.snapshot(session, p, ontology, body)
                return self.store(
                    session,
                    p,
                    ontology,
                    body.schema_version,
                    "asserted",
                    content,
                    provenance=provenance,
                ).id

    def access(
        self, session: Session, p: Principal, row: SemanticArtifact, *, fresh: bool = False
    ) -> Literal["SCHEMA_ONLY", "CURRENT", "STALE", "UNKNOWN"]:
        manifest = ArtifactManifest.model_validate_json(row.manifest_json)
        provenance = manifest.provenance
        source = provenance.get("asserted_artifact")
        if source is not None:
            secondary = provenance.get("secondary_artifact")
            if secondary is not None:
                self.row(session, p, row.ontology_id, UUID(str(secondary)))
            asserted = self.row(session, p, row.ontology_id, UUID(str(source)))
            source_state = self.access(session, p, asserted, fresh=fresh)
            if (
                manifest.engine_version != ENGINE_VERSION
                or manifest.compiler_version != COMPILER_VERSION
            ):
                if fresh:
                    raise ApplicationError(
                        "stale_inputs", "Semantic execution version changed", 409
                    )
                return "STALE"
            return source_state
        if row.kind != "asserted":
            # Change reports inherit BOTH schema artifact permissions.
            for key in ("primary_artifact", "secondary_artifact"):
                if key in provenance:
                    self.row(session, p, row.ontology_id, UUID(str(provenance[key])))
            return "SCHEMA_ONLY"
        self.authorizer.require(p, "semantic:export", f"{p.tenant_id}/{row.ontology_id}/semantic")
        body = ExportInput.model_validate(provenance["export"])
        root = self.ontology(session, p, row.ontology_id)
        # After activation, old policy predicates may no longer typecheck: deny payload, retain
        # history.
        if root.active_version != row.schema_version:
            if fresh:
                raise ApplicationError("stale_schema", "Active schema changed", 409)
            raise ApplicationError(
                "stale_schema", "Historical payload requires an active compatible schema", 409
            )
        current, observed = self.snapshot(session, p, row.ontology_id, body)
        if observed["policy_hash"] != provenance["policy_hash"]:
            raise ApplicationError(
                "semantic_input_forbidden", "Input policy changed; export again", 403
            )
        selected = cast(dict[str, list[str]], provenance["selected"])
        visible = cast(dict[str, list[str]], observed["selected"])
        if any(set(keys) - set(visible.get(kind, [])) for kind, keys in selected.items()):
            raise ApplicationError(
                "semantic_input_forbidden",
                "Input identities are no longer in the authorized selection",
                403,
            )
        state: Literal["CURRENT", "STALE"] = (
            "CURRENT"
            if (digest(current) == row.output_hash and observed == provenance)
            else "STALE"
        )
        if fresh and state != "CURRENT":
            raise ApplicationError("stale_inputs", "Export inputs changed; export again", 409)
        return state

    def get(self, p: Principal, ontology: str, key: UUID) -> ArtifactView:
        with self.operation(p, "semantic:read", f"{ontology}/semantic/artifacts/{key}") as session:
            row = self.row(session, p, ontology, key)
            return ArtifactView(
                manifest=ArtifactManifest.model_validate_json(row.manifest_json),
                content=row.content,
                freshness=self.access(session, p, row),
            )

    @staticmethod
    def job_view(row: SemanticJob) -> JobView:
        return JobView(
            id=row.id,
            schema_version=row.schema_version,
            principal_id=row.principal_id,
            request=JobInput.model_validate_json(row.request_json),
            status=row.status,
            attempts=row.attempts,
            created_at=row.created_at,
            completed_at=row.completed_at,
            last_error=row.last_error,
            outputs=[UUID(key) for key in row.outputs],
            history=row.history,
        )

    def job_row(self, session: Session, p: Principal, ontology: str, key: UUID) -> SemanticJob:
        row = session.get(SemanticJob, (p.tenant_id, ontology, key))
        if row is None or row.principal_id != p.principal_id:
            raise missing("Semantic job")
        return row

    def submit(self, p: Principal, ontology: str, body: JobInput) -> JobView:
        with self.operation(p, "semantic:execute", f"{ontology}/semantic/jobs") as session:
            # Serialize content-key deduplication using the established ontology lock.
            self.ontology(session, p, ontology, write=True)
            primary = self.row(session, p, ontology, body.primary_artifact)
            secondary = self.row(session, p, ontology, body.secondary_artifact)
            expected = {
                "validation": ("asserted", "shapes"),
                "reasoning": ("asserted", "ontology"),
                "change": ("ontology", "ontology"),
            }[body.operation]
            if (primary.kind, secondary.kind) != expected:
                raise ApplicationError(
                    "invalid_semantic_inputs", "Wrong input artifact categories", 422
                )
            if body.operation != "change" and primary.schema_version != secondary.schema_version:
                raise ApplicationError("stale_schema", "Input schema versions differ", 409)
            self.access(session, p, primary, fresh=True)
            self.access(session, p, secondary, fresh=True)
            fingerprint = digest(
                encode([body.model_dump(mode="json"), ENGINE_VERSION, COMPILER_VERSION]).encode()
            )
            row = session.scalar(
                select(SemanticJob).where(
                    SemanticJob.tenant_id == p.tenant_id,
                    SemanticJob.ontology_id == ontology,
                    SemanticJob.principal_id == p.principal_id,
                    SemanticJob.fingerprint == fingerprint,
                )
            )
            if row is None:
                row = SemanticJob(
                    tenant_id=p.tenant_id,
                    ontology_id=ontology,
                    id=uuid4(),
                    principal_id=p.principal_id,
                    schema_version=primary.schema_version,
                    primary_artifact=primary.id,
                    secondary_artifact=secondary.id,
                    request_json=body.model_dump_json(),
                    fingerprint=fingerprint,
                )
                session.add(row)
                session.flush()
            return self.job_view(row)

    def job(self, p: Principal, ontology: str, key: UUID) -> JobView:
        with self.operation(p, "semantic:history", f"{ontology}/semantic/jobs/{key}") as session:
            return self.job_view(self.job_row(session, p, ontology, key))

    def jobs(self, p: Principal, ontology: str, limit: int = 50, offset: int = 0) -> list[JobView]:
        self.page(limit, offset)
        with self.operation(p, "semantic:history", f"{ontology}/semantic/jobs") as session:
            rows = session.scalars(
                select(SemanticJob)
                .where(
                    SemanticJob.tenant_id == p.tenant_id,
                    SemanticJob.ontology_id == ontology,
                    SemanticJob.principal_id == p.principal_id,
                )
                .order_by(SemanticJob.created_at, SemanticJob.id)
                .limit(limit)
                .offset(offset)
            )
            return [self.job_view(row) for row in rows]

    @staticmethod
    def page(limit: int, offset: int) -> None:
        if not 1 <= limit <= 100 or not 0 <= offset <= 10000:
            raise ApplicationError("invalid_page", "Limit 1–100 and offset 0–10000 required", 422)

    def cancel(self, p: Principal, ontology: str, key: UUID) -> JobView:
        with self.operation(p, "semantic:cancel", f"{ontology}/semantic/jobs/{key}") as session:
            row = self.job_row(session, p, ontology, key)
            session.refresh(row, with_for_update=True)
            if row.status in {"PENDING", "RUNNING"}:
                row.history = row.history + [
                    {"event": "CANCELLED", "at": datetime.now(UTC).isoformat()}
                ]
                row.status, row.token, row.lease_until = "CANCELLED", None, None
                row.completed_at = datetime.now(UTC)
                session.flush()
            return self.job_view(row)

    def approval(self, session: Session, row: SemanticArtifact) -> str:
        result = session.scalar(
            select(SemanticApproval.state)
            .where(
                SemanticApproval.tenant_id == row.tenant_id,
                SemanticApproval.ontology_id == row.ontology_id,
                SemanticApproval.set_id == row.id,
            )
            .order_by(SemanticApproval.created_at.desc(), SemanticApproval.id.desc())
            .limit(1)
        )
        return result or "PENDING"

    def approve(self, p: Principal, ontology: str, key: UUID, body: ApprovalInput) -> str:
        with self.operation(
            p, "semantic:approve", f"{ontology}/semantic/artifacts/{key}"
        ) as session:
            self.ontology(session, p, ontology, write=True)
            row = self.row(session, p, ontology, key)
            if row.kind != "derived":
                raise ApplicationError(
                    "invalid_fact_set", "Approval requires a derived fact set", 422
                )
            self.access(session, p, row, fresh=True)
            session.add(
                SemanticApproval(
                    tenant_id=p.tenant_id,
                    ontology_id=ontology,
                    set_id=key,
                    id=uuid4(),
                    principal_id=p.principal_id,
                    state=body.state,
                )
            )
            return body.state

    def facts(
        self, p: Principal, ontology: str, key: UUID, limit: int = 50, offset: int = 0
    ) -> list[FactView]:
        self.page(limit, offset)
        with self.operation(p, "semantic:read", f"{ontology}/semantic/artifacts/{key}") as session:
            row = self.row(session, p, ontology, key)
            if row.kind != "derived":
                raise ApplicationError("invalid_fact_set", "Expected a derived fact set", 422)
            state = self.access(session, p, row)
            manifest = ArtifactManifest.model_validate_json(row.manifest_json)
            prov = manifest.provenance
            rows = session.scalars(
                select(DerivedFact)
                .where(
                    DerivedFact.tenant_id == p.tenant_id,
                    DerivedFact.ontology_id == ontology,
                    DerivedFact.set_id == key,
                )
                .order_by(DerivedFact.id)
                .limit(limit)
                .offset(offset)
            )
            return [
                FactView(
                    id=fact.id,
                    subject=fact.subject,
                    predicate=fact.predicate,
                    object=fact.object,
                    reasoning_job=fact.job_id,
                    asserted_hash=manifest.input_hashes["asserted"],
                    schema_version=row.schema_version,
                    engine_version=manifest.engine_version,
                    profile=prov["profile"],
                    derived_at=manifest.created_at,
                    approval=self.approval(session, row),
                    freshness=state,
                )
                for fact in rows
            ]

    def approval_history(
        self, p: Principal, ontology: str, key: UUID, limit: int = 50, offset: int = 0
    ) -> list[ApprovalEvent]:
        self.page(limit, offset)
        with self.operation(
            p, "semantic:history", f"{ontology}/semantic/artifacts/{key}"
        ) as session:
            row = self.row(session, p, ontology, key)
            if row.kind != "derived":
                raise ApplicationError("invalid_fact_set", "Expected a derived fact set", 422)
            rows = session.scalars(
                select(SemanticApproval)
                .where(
                    SemanticApproval.tenant_id == p.tenant_id,
                    SemanticApproval.ontology_id == ontology,
                    SemanticApproval.set_id == key,
                )
                .order_by(SemanticApproval.created_at, SemanticApproval.id)
                .limit(limit)
                .offset(offset)
            )
            return [ApprovalEvent.model_validate(event) for event in rows]
