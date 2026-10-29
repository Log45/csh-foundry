"""Governed authoring gateway composing the existing authoritative registry transaction."""

import json
from uuid import UUID, uuid4

from rdflib import OWL, RDF, Graph, URIRef
from rdflib.term import Node
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ontology_platform.db.governance import GovernedService, missing
from ontology_platform.db.models import OntologyImport, VocabularyBinding
from ontology_platform.errors import ApplicationError
from ontology_platform.interoperability.contracts import (
    ClassMapping,
    ExportView,
    ImportInput,
    ImportView,
    LinkMapping,
    MappingInput,
    VocabularyTerm,
)
from ontology_platform.interoperability.mapping import project, target
from ontology_platform.interoperability.parser import parse_import, serialize_graph
from ontology_platform.metadata.compatibility import compare
from ontology_platform.metadata.service import RegistryService
from ontology_platform.metadata.storage import definition_of, version_row
from ontology_platform.security.interfaces import Principal
from ontology_platform.semantic.compiler import compile_schema, digest, serialize, term
from ontology_platform.semantic.contracts import Diagnostic


def page(limit: int, offset: int) -> None:
    if not 1 <= limit <= 100 or not 0 <= offset <= 10000:
        raise ApplicationError("invalid_page", "Use limit 1–100 and offset 0–10000", 422)


class InteroperabilityService(GovernedService):
    def row(self, session: Session, p: Principal, ontology: str, key: UUID) -> OntologyImport:
        self.authorizer.require(p, "schema:read", f"{p.tenant_id}/{ontology}")
        row = session.get(OntologyImport, (p.tenant_id, ontology, key))
        if row is None or row.principal_id != p.principal_id:
            raise missing("Ontology import")
        if digest(row.original.encode()) != row.input_hash:
            raise ApplicationError("artifact_integrity", "Import artifact integrity failed", 409)
        return row

    def get(self, p: Principal, ontology: str, key: UUID) -> ImportView:
        with self.operation(p, "ontology:import:read", ontology) as session:
            return ImportView.model_validate_json(self.row(session, p, ontology, key).result_json)

    def original(self, p: Principal, ontology: str, key: UUID) -> str:
        with self.operation(p, "ontology:import:read", ontology) as session:
            return self.row(session, p, ontology, key).original

    def diagnostics(
        self, p: Principal, ontology: str, key: UUID, limit: int = 50, offset: int = 0
    ) -> list[Diagnostic]:
        page(limit, offset)
        with self.operation(p, "ontology:import:read", ontology) as session:
            data = json.loads(self.row(session, p, ontology, key).diagnostics_json)
            return [Diagnostic.model_validate(d) for d in data[offset : offset + limit]]

    def vocabulary(
        self, p: Principal, ontology: str, key: UUID, limit: int = 50, offset: int = 0
    ) -> list[VocabularyTerm]:
        page(limit, offset)
        with self.operation(p, "ontology:import:read", ontology) as session:
            graph = Graph().parse(data=self.row(session, p, ontology, key).graph, format="nt")
            terms: dict[str, set[str]] = {}
            for subject, kind in graph.subject_objects(RDF.type):
                if isinstance(subject, URIRef):
                    terms.setdefault(str(subject), set()).add(str(kind))
            return [
                VocabularyTerm(iri=iri, kinds=sorted(terms[iri]))
                for iri in sorted(terms)[offset : offset + limit]
            ]

    def import_ontology(self, p: Principal, ontology: str, body: ImportInput) -> ImportView:
        # Authorize target before spending parser resources; no ontology lock while parsing.
        with self.operation(p, "ontology:import", ontology) as session:
            self.ontology(session, p, ontology)
            self.authorizer.require(p, "schema:read", f"{p.tenant_id}/{ontology}")
            if body.mode == "CREATE_DRAFT":
                self.authorizer.require(p, "schema:write", f"{p.tenant_id}/{ontology}")
        graph = parse_import(body.content, body.format)
        with self.operation(p, "ontology:import", ontology) as session:
            root = self.ontology(session, p, ontology, write=True)
            base_version = body.base_version or root.active_version
            if base_version is None:
                raise ApplicationError(
                    "base_required", "Select an existing canonical base version", 422
                )
            row = version_row(session, root, base_version)
            self.authorizer.require(
                p, "schema:read", f"{p.tenant_id}/{ontology}/versions/{base_version}"
            )
            if body.expected_base_hash is not None and body.expected_base_hash != row.content_hash:
                raise ApplicationError("stale_import_base", "Canonical import base changed", 409)
            if (
                body.mode == "CREATE_DRAFT"
                and row.status == "DRAFT"
                and body.expected_base_hash is None
            ):
                raise ApplicationError(
                    "base_hash_required", "Draft bases require expected_base_hash", 409
                )
            base = definition_of(row)

            def conflict(iri: str, target: str) -> bool:
                found = session.scalars(
                    select(VocabularyBinding).where(
                        VocabularyBinding.tenant_id == p.tenant_id,
                        VocabularyBinding.ontology_id == ontology,
                        or_(
                            VocabularyBinding.iri_hash == digest(iri.encode()),
                            VocabularyBinding.target_hash == digest(target.encode()),
                        ),
                    )
                ).all()
                return any(r.iri != iri or r.target != target for r in found)

            candidate, diagnostics, bindings, supported, changes = project(
                graph, base, body, conflict
            )
            ontologies = sorted(set(graph.subjects(RDF.type, OWL.Ontology)), key=str)
            versions = sorted(set(graph.objects(None, OWL.versionIRI)), key=str)
            if len(ontologies) > 1 or len(versions) > 1:
                diagnostics.append(
                    Diagnostic(
                        code="mapping_conflict",
                        construct="ontology",
                        message="Multiple ontology or version IRIs require separate imports",
                    )
                )
            conflicts = sum(d.code != "semantic_only" for d in diagnostics)
            key = uuid4()
            reference = f"/api/v1/ontologies/{ontology}/interchange/imports/{key}"
            active = (
                definition_of(version_row(session, root, root.active_version))
                if root.active_version
                else None
            )
            comparison = compare(active, candidate) if candidate else None
            result = ImportView(
                id=key,
                ontology_id=ontology,
                base_version=base_version,
                base_hash=row.content_hash,
                artifact_reference=reference + "/original",
                input_hash=digest(body.content.encode()),
                ontology_iri=str(ontologies[0]) if len(ontologies) == 1 else None,
                version_iri=str(versions[0]) if len(versions) == 1 else None,
                status="CONFLICT" if conflicts else "PREVIEWED",
                supported_construct_count=supported,
                preserved_semantic_construct_count=len(graph) - supported,
                unsupported_construct_count=len(graph) - supported,
                conflict_count=conflicts,
                diagnostic_count=len(diagnostics),
                diagnostics=diagnostics[:100],
                diagnostics_truncated=len(diagnostics) > 100,
                diagnostic_reference=reference + "/diagnostics",
                compatibility=comparison,
                proposed_definition=candidate,
                changes=changes,
                draft_version=None,
            )
            if body.mode == "CREATE_DRAFT" and not conflicts and candidate is not None:
                registry = RegistryService(self.sessions, self.authorizer, session=session)
                registry.draft(p, ontology, candidate)
                result.status, result.draft_version = "DRAFT_CREATED", candidate.version
            if (
                len(result.model_dump_json().encode()) > 262144
                or len(body.model_dump_json().encode()) > 524288
                or len(json.dumps(bindings).encode()) > 262144
            ):
                raise ApplicationError(
                    "import_resource_limit", "Import proposal exceeds storage bound", 422
                )
            session.add(
                OntologyImport(
                    tenant_id=p.tenant_id,
                    ontology_id=ontology,
                    id=key,
                    principal_id=p.principal_id,
                    draft_version=result.draft_version,
                    canonical_hash=digest(candidate.canonical_json().encode())
                    if result.draft_version and candidate
                    else None,
                    bindings_json=json.dumps(bindings),
                    format=body.format,
                    original=body.content,
                    input_hash=result.input_hash,
                    graph=serialize_graph(graph),
                    request_json=body.model_dump_json(),
                    result_json=result.model_dump_json(by_alias=True),
                    diagnostics_json=json.dumps([d.model_dump(by_alias=True) for d in diagnostics]),
                )
            )
            session.flush()
            if result.status == "DRAFT_CREATED":
                for iri, target in bindings.items():
                    ihash = digest(iri.encode())
                    if session.get(VocabularyBinding, (p.tenant_id, ontology, ihash)) is None:
                        session.add(
                            VocabularyBinding(
                                tenant_id=p.tenant_id,
                                ontology_id=ontology,
                                iri_hash=ihash,
                                iri=iri,
                                target=target,
                                target_hash=digest(target.encode()),
                                import_id=key,
                            )
                        )
            session.flush()
            return result

    def export(self, p: Principal, ontology: str, version: str) -> ExportView:
        with self.operation(p, "schema:export", ontology) as session:
            self.authorizer.require(
                p, "schema:read", f"{p.tenant_id}/{ontology}/versions/{version}"
            )
            root = self.ontology(session, p, ontology)
            row = version_row(session, root, version)
            if row.status != "PUBLISHED":
                raise ApplicationError(
                    "unpublished_schema", "Export requires a published schema", 409
                )
            schema = definition_of(row)
            content, _, diagnostics = compile_schema(schema)
            if (
                len(schema.object_types) > 32
                or len(schema.link_types) > 64
                or any(len(t.properties) > 64 for t in schema.object_types)
            ):
                raise ApplicationError(
                    "import_resource_limit", "Interchange mapping limit exceeded", 422
                )
            replacements: dict[Node, Node] = {}
            provenance = session.scalar(
                select(OntologyImport).where(
                    OntologyImport.tenant_id == p.tenant_id,
                    OntologyImport.ontology_id == ontology,
                    OntologyImport.draft_version == version,
                )
            )
            imported: dict[str, str] = {}
            if provenance is not None and provenance.canonical_hash == row.content_hash:
                imported = {path: iri for iri, path in json.loads(provenance.bindings_json).items()}
            elif provenance is not None:
                diagnostics.append(
                    Diagnostic(
                        code="import_mapping_stale",
                        construct=version,
                        message="Canonical draft changed after import; using generated vocabulary",
                    )
                )

            def vocabulary(kind: str, *ids: str) -> str:
                generated = term(schema.namespace, kind, *ids)
                iri = imported.get(target(kind, *ids))
                if iri is not None:
                    replacements[generated] = URIRef(iri)
                    return iri
                return str(generated)

            classes = []
            for typed in schema.object_types:
                # Unsupported properties stay canonical; omit their reimport mappings.
                if any(prop.array or prop.data_type == "json" for prop in typed.properties):
                    continue
                classes.append(
                    ClassMapping(
                        iri=vocabulary("class", typed.id),
                        definition=typed,
                        property_iris={
                            prop.id: vocabulary("property", typed.id, prop.id)
                            for prop in typed.properties
                        },
                    )
                )
            eligible = {c.definition.id for c in classes}
            mappings = MappingInput(
                classes=tuple(classes),
                links=tuple(
                    LinkMapping(iri=vocabulary("link", link.id), definition=link)
                    for link in schema.link_types
                    if link.source_type in eligible and link.target_type in eligible
                ),
            )
            if len(mappings.model_dump_json().encode()) > 262144:
                raise ApplicationError(
                    "import_resource_limit", "Export mapping exceeds 256 KiB", 422
                )
            graph = Graph().parse(data=content, format="turtle")
            mapped = Graph()
            for s, pred, obj in graph:
                mapped.add((replacements.get(s, s), pred, replacements.get(obj, obj)))
            for link in schema.link_types:
                if link.inverse_name:
                    mapped.add(
                        (
                            term(schema.namespace, "inverse-link", link.id),
                            RDF.type,
                            OWL.ObjectProperty,
                        )
                    )
            content = serialize(mapped)
            return ExportView(
                content=content.decode(),
                output_hash=digest(content),
                canonical_hash=row.content_hash,
                mappings=mappings,
                diagnostics=diagnostics,
            )
