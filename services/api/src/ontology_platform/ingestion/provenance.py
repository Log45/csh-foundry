"""Public bounded provenance projection for already authorized operational selections."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ontology_platform.db.models import IngestionStage, SourceObject
from ontology_platform.security.interfaces import Authorizer, Principal


def export_provenance(
    session: Session,
    authorizer: Authorizer,
    p: Principal,
    ontology: str,
    selected: dict[str, list[str]],
) -> dict[str, object]:
    sources = set()
    runs = set()
    for kind, keys in selected.items():
        rows = session.scalars(
            select(SourceObject)
            .where(
                SourceObject.tenant_id == p.tenant_id,
                SourceObject.ontology_id == ontology,
                SourceObject.object_type == kind,
                SourceObject.object_id.in_(keys),
            )
            .limit(1000)
        )
        for row in rows:
            authorizer.require(
                p, "source:read", f"{p.tenant_id}/{ontology}/sources/{row.source_id}"
            )
            sources.add((row.source_id, row.source_version))
        # These are retained staging associations, NOT a claim of exact historical reconstruction.
        refs = session.scalars(
            select(IngestionStage.run_id)
            .where(
                IngestionStage.tenant_id == p.tenant_id,
                IngestionStage.ontology_id == ontology,
                IngestionStage.object_type == kind,
                IngestionStage.object_id.in_(keys),
                IngestionStage.state == "DONE",
            )
            .distinct()
            .order_by(IngestionStage.run_id)
            .limit(101)
        )
        for key in refs:
            authorizer.require(
                p, "ingestion:history", f"{p.tenant_id}/{ontology}/ingestion/runs/{key}"
            )
            runs.add(str(key))
    return {
        "source_versions": [list(ref) for ref in sorted(sources)],
        "available_ingestion_runs": sorted(runs)[:100],
        "run_refs_truncated": len(runs) > 100,
        "run_refs_scope": "retained staging associations; exact"
        " operational revision is the export boundary",
    }
