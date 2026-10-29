"""Leased semantic execution: engine work outside transactions, fenced atomic completion."""

import time
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from rdflib import BNode, Graph, URIRef
from rdflib.compare import to_canonical_graph
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ontology_platform.db.models import DerivedFact, SemanticArtifact, SemanticJob
from ontology_platform.errors import ApplicationError
from ontology_platform.ingestion.worker import clock
from ontology_platform.security.interfaces import Principal
from ontology_platform.semantic.compiler import parse, serialize, triple_id
from ontology_platform.semantic.contracts import JobInput
from ontology_platform.semantic.engine import (
    ENGINE_COMMIT,
    ENGINE_VERSION,
    SemanticEngine,
    SemanticResult,
)
from ontology_platform.semantic.service import SemanticService, encode


class SemanticWorker(SemanticService):
    def __init__(self, *args: Any, engine: SemanticEngine, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.engine = engine

    def claim(self, p: Principal, ontology: str) -> tuple[UUID, UUID] | None:
        with self.operation(p, "semantic:claim", f"{ontology}/semantic/jobs") as session:
            now = clock(session)
            row = session.scalar(
                select(SemanticJob)
                .where(
                    SemanticJob.tenant_id == p.tenant_id,
                    SemanticJob.ontology_id == ontology,
                    SemanticJob.principal_id == p.principal_id,
                    or_(
                        SemanticJob.status == "PENDING",
                        (SemanticJob.status == "RUNNING") & (SemanticJob.lease_until < now),
                    ),
                )
                .order_by(SemanticJob.created_at, SemanticJob.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            self.authorizer.require(
                p, "semantic:execute", f"{p.tenant_id}/{ontology}/semantic/jobs/{row.id}"
            )
            if row.attempts >= 3:
                row.status, row.last_error, row.token, row.lease_until = (
                    "FAILED",
                    "lease_exhausted",
                    None,
                    None,
                )
                row.completed_at = now
                return None
            row.status, row.token = "RUNNING", uuid4()
            row.attempts += 1
            row.history = row.history + [
                {"event": "CLAIMED", "attempt": row.attempts, "at": now.isoformat()}
            ]
            row.lease_until = now + timedelta(seconds=60)
            return row.id, row.token

    def fenced(
        self, session: Session, p: Principal, ontology: str, key: UUID, token: UUID
    ) -> SemanticJob:
        row = self.job_row(session, p, ontology, key)
        session.refresh(row, with_for_update=True)
        if (
            row.status != "RUNNING"
            or row.token != token
            or row.lease_until is None
            or row.lease_until <= clock(session)
        ):
            raise ApplicationError("lease_lost", "Semantic worker lease lost", 409)
        return row

    def renew(self, p: Principal, ontology: str, key: UUID, token: UUID) -> None:
        with self.operation(p, "semantic:claim", f"{ontology}/semantic/jobs/{key}") as session:
            row = self.fenced(session, p, ontology, key, token)
            row.lease_until = clock(session) + timedelta(seconds=60)

    def inputs(
        self, session: Session, p: Principal, row: SemanticJob
    ) -> tuple[SemanticArtifact, SemanticArtifact]:
        primary = self.row(session, p, row.ontology_id, row.primary_artifact)
        secondary = self.row(session, p, row.ontology_id, row.secondary_artifact)
        self.access(session, p, primary, fresh=True)
        self.access(session, p, secondary, fresh=True)
        return primary, secondary

    def execute(self, p: Principal, ontology: str, key: UUID, token: UUID) -> None:
        with self.operation(p, "semantic:execute", f"{ontology}/semantic/jobs/{key}") as session:
            row = self.fenced(session, p, ontology, key, token)
            primary, secondary = self.inputs(session, p, row)
            body = JobInput.model_validate_json(row.request_json)
            first, second = primary.content.encode(), secondary.content.encode()
        # No ontology locks or operational PostgreSQL transactions during subprocess work.
        parse(first)
        parse(second, "invalid_shacl" if body.operation == "validation" else "invalid_rdf")
        started = time.monotonic()
        if body.operation == "validation":
            result = self.engine.validate_shapes(second, first)
        elif body.operation == "reasoning":
            result = self.engine.derive(second, first, body.profile)
        else:
            result = self.engine.analyze_change(first, second)
        duration = time.monotonic() - started
        if result.engine_version != ENGINE_VERSION or result.engine_commit != ENGINE_COMMIT:
            raise ApplicationError("semantic_version_mismatch", "Unexpected engine version", 503)
        with self.operation(p, "semantic:execute", f"{ontology}/semantic/jobs/{key}") as session:
            self.ontology(session, p, ontology, write=True)
            row = self.fenced(session, p, ontology, key, token)
            primary, secondary = self.inputs(session, p, row)
            outputs = self.persist(session, p, row, primary, secondary, result, duration)
            session.flush()
            if row.lease_until is None or row.lease_until <= clock(session):
                raise ApplicationError("lease_lost", "Lease expired before completion", 409)
            row.history = row.history + [{"event": "COMPLETED", "at": clock(session).isoformat()}]
            row.outputs = [str(item) for item in outputs]
            row.status, row.token, row.lease_until = "COMPLETED", None, None
            row.last_error = None
            row.completed_at = clock(session)

    def persist(
        self,
        session: Session,
        p: Principal,
        row: SemanticJob,
        primary: SemanticArtifact,
        secondary: SemanticArtifact,
        result: SemanticResult,
        duration: float,
    ) -> list[UUID]:
        body = JobInput.model_validate_json(row.request_json)
        provenance: dict[str, object] = {
            "job_id": str(row.id),
            "primary_artifact": str(primary.id),
            "secondary_artifact": str(secondary.id),
            "profile": body.profile,
        }
        if body.operation != "change":
            provenance["asserted_artifact"] = str(primary.id)
        hashes = {
            "asserted" if body.operation != "change" else "previous": primary.output_hash,
            "shapes" if body.operation == "validation" else "ontology": secondary.output_hash,
        }
        report: dict[str, object] = {
            "job_id": str(row.id),
            "engine_version": ENGINE_VERSION,
            "input_hashes": hashes,
            "duration_seconds": duration,
            "profile": body.profile,
        }
        outputs = []
        if body.operation == "validation":
            data = result.records[-1]["result"]
            if not isinstance(data, dict) or data.get("conforms") not in {True, False, None}:
                raise ApplicationError("semantic_failed", "Malformed validation response", 502)
            violations = data.get("violations", [])
            if not isinstance(violations, list):
                raise ApplicationError("semantic_failed", "Malformed validation violations", 502)
            # Only semantic report fields; never load paths, engine stderr or command diagnostics.
            report.update(
                {
                    "conforms": data.get("conforms"),
                    "violation_count": data.get("violation_count", len(violations)),
                    "violations": violations[:100],
                    "details_truncated": len(violations) > 100,
                    "skipped_constraints": data.get("skipped_constraints", []),
                    "unmatched_shapes": data.get("unmatched_shapes", []),
                    "validation_profile": "open-ontologies-shacl",
                }
            )
        elif body.operation == "change":
            report["analysis"] = result.records[-1]["result"]
            report["scope"] = (
                "native graph/schema diff; not a proof of operational migration safety"
            )
        else:
            # Certificate lines are engine-produced derivations, including reliable rule
            # identifiers.
            graph = Graph()
            certificate = result.files["certificate/derivations.tsv"]
            conclusions = []
            for line in certificate.splitlines():
                fields = line.split("\t")
                if len(fields) < 4:
                    raise ApplicationError(
                        "semantic_failed", "Malformed derivation certificate", 502
                    )
                conclusion = " ".join(fields[1:4]) + " ."
                conclusions.append(conclusion)
            graph.parse(data="\n".join(conclusions), format="nt")
            # Stable canonicalization for the RESULT graph, not asserted/inferred guessing from
            # closure.
            canonical = to_canonical_graph(graph)
            graph = Graph()
            scope = hashes["asserted"] + ":" + hashes["ontology"] + ":" + body.profile
            for triple in canonical:
                converted = [
                    URIRef("urn:foundry:derived:" + scope + ":" + str(node))
                    if isinstance(node, BNode)
                    else node
                    for node in triple
                ]
                graph.add((converted[0], converted[1], converted[2]))
            provenance["blank_node_mapping"] = (
                "canonical-result-local-skolem-v1; original certificate retained"
            )
            content = serialize(graph)
            derived = self.store(
                session,
                p,
                row.ontology_id,
                row.schema_version,
                "derived",
                content,
                inputs=hashes,
                provenance=provenance,
            )
            outputs.append(derived.id)
            for s, pred, obj in graph:
                session.add(
                    DerivedFact(
                        tenant_id=p.tenant_id,
                        ontology_id=row.ontology_id,
                        set_id=derived.id,
                        id=triple_id(s, pred, obj),
                        subject=s.n3(),
                        predicate=pred.n3(),
                        object=obj.n3(),
                        job_id=row.id,
                    )
                )
            proof = self.store(
                session,
                p,
                row.ontology_id,
                row.schema_version,
                "proof",
                encode(
                    {
                        "format": "oo-cert/1",
                        "verification": "NOT RUN",
                        "checker": "Lean oo-cert unavailable",
                        "files": {
                            k: v for k, v in result.files.items() if k.startswith("certificate/")
                        },
                    }
                ).encode(),
                inputs=hashes,
                provenance=provenance,
            )
            outputs.append(proof.id)
            engine_summary = result.records[-2]["result"]
            if not isinstance(engine_summary, dict):
                raise ApplicationError("semantic_failed", "Malformed reasoning response", 502)
            report["engine_summary"] = {
                key: engine_summary.get(key)
                for key in ("inferred_count", "fixpoint_reached", "iterations", "profile_used")
            }
            report.update(
                {
                    "derived_count": len(graph),
                    "derived_artifact": str(derived.id),
                    "proof_artifact": str(proof.id),
                    "proof_verification": "NOT RUN",
                }
            )
        artifact = self.store(
            session,
            p,
            row.ontology_id,
            row.schema_version,
            body.operation,
            encode(report).encode(),
            inputs=hashes,
            provenance=provenance,
        )
        outputs.append(artifact.id)
        return outputs

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
        with self.operation(p, "semantic:execute", f"{ontology}/semantic/jobs/{key}") as session:
            row = self.job_row(session, p, ontology, key)
            session.refresh(row, with_for_update=True)
            if (
                row.status != "RUNNING"
                or row.token != token
                or row.lease_until is None
                or row.lease_until <= clock(session)
            ):
                return
            row.status = "PENDING" if retryable and row.attempts < 3 else "FAILED"
            row.history = row.history + [
                {"event": "ERROR", "code": code[:100], "at": clock(session).isoformat()}
            ]
            row.last_error = code[:100]
            row.token, row.lease_until = None, None
            if row.status == "FAILED":
                row.completed_at = clock(session)

    def run_one(self, p: Principal, ontology: str) -> UUID | None:
        claim = self.claim(p, ontology)
        if claim is None:
            return None
        key, token = claim
        try:
            self.execute(p, ontology, key, token)
        except ApplicationError as exc:
            if exc.code != "lease_lost":
                self.fail(
                    p,
                    ontology,
                    key,
                    token,
                    exc.code,
                    retryable=exc.code in {"semantic_unavailable", "semantic_timeout"},
                )
        except (SQLAlchemyError, OSError, ValueError, KeyError, TypeError):
            self.fail(p, ontology, key, token, "semantic_worker_error", retryable=True)
        return key
