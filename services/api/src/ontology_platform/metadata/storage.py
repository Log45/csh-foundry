"""Public registry persistence helpers used inside a governed unit of work."""

import hashlib

from ontology_schema.models import OntologyDefinition
from sqlalchemy.orm import Session

from ontology_platform.contracts import VersionView
from ontology_platform.db.governance import missing
from ontology_platform.db.models import Ontology, Version
from ontology_platform.errors import ApplicationError


def digest(definition: OntologyDefinition) -> str:
    return hashlib.sha256(definition.canonical_json().encode()).hexdigest()


def version_row(session: Session, ontology: Ontology, version: str) -> Version:
    row = session.get(Version, (ontology.tenant_id, ontology.id, version))
    if row is None:
        raise missing("Version")
    return row


def definition_of(row: Version) -> OntologyDefinition:
    return OntologyDefinition.model_validate_json(row.definition_json)


def active_definition(session: Session, ontology: Ontology) -> OntologyDefinition:
    if ontology.active_version is None:
        raise ApplicationError("schema_inactive", "Activate a published schema first", 409)
    return definition_of(version_row(session, ontology, ontology.active_version))


def version_view(row: Version) -> VersionView:
    return VersionView(
        definition=definition_of(row),
        status=row.status,
        content_hash=row.content_hash,
        published_at=row.published_at,
        published_by=row.published_by,
    )
