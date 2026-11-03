"""Registered type adapters: immutable canonical definitions remain authoritative."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ontology_platform.db.governance import missing
from ontology_platform.db.models import Version
from ontology_platform.metadata.storage import definition_of
from ontology_platform.security.interfaces import Authorizer, Principal


@dataclass(frozen=True)
class OntologyAdapter:
    collection: str | None

    def entities(
        self, session: Session, p: Principal, ontology: str, version: str, authorizer: Authorizer
    ) -> dict[str, str]:
        authorizer.require(p, "schema:read", f"{p.tenant_id}/{ontology}")
        row = session.get(Version, (p.tenant_id, ontology, version))
        if row is None or row.status != "PUBLISHED":
            raise missing("Published ontology asset")
        definition = definition_of(row)
        if self.collection is None:
            return {version: f"{definition.name} {version}"}
        return {item.id: item.name for item in getattr(definition, self.collection)}


HANDLERS = {
    "ONTOLOGY_OBJECT_TYPE": OntologyAdapter("object_types"),
    "ONTOLOGY_LINK_TYPE": OntologyAdapter("link_types"),
    "ONTOLOGY_ACTION": OntologyAdapter("action_types"),
    "ONTOLOGY_VERSION": OntologyAdapter(None),
}
