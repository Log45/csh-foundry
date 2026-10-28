"""Forward-edge persistence and cardinality validation; no redundant inverse edges."""

from collections import Counter
from uuid import UUID

from ontology_schema.models import LinkTypeDefinition, OntologyDefinition
from sqlalchemy import select
from sqlalchemy.orm import Session

from ontology_platform.db.models import Link
from ontology_platform.errors import ApplicationError


def link_type(definition: OntologyDefinition, type_id: str) -> LinkTypeDefinition:
    result = next((t for t in definition.link_types if t.id == type_id), None)
    if result is None:
        raise ApplicationError("unknown_link_type", "Link type is not in the active schema", 422)
    return result


def validate_cardinality(definition: LinkTypeDefinition, links: list[Link]) -> None:
    sources = Counter((link.source_object_type_id, link.source_object_id) for link in links)
    targets = Counter((link.target_object_type_id, link.target_object_id) for link in links)
    if (
        definition.cardinality in {"one_to_one", "many_to_one"}
        and any(n > 1 for n in sources.values())
        or definition.cardinality in {"one_to_one", "one_to_many"}
        and any(n > 1 for n in targets.values())
    ):
        raise ApplicationError("cardinality_conflict", "Link cardinality would be violated", 409)


def validate_live_links(
    session: Session, tenant_id: UUID, ontology_id: str, definition: OntologyDefinition
) -> list[Link]:
    links = list(
        session.scalars(
            select(Link)
            .where(Link.tenant_id == tenant_id, Link.ontology_id == ontology_id)
            .limit(5001)
        )
    )
    if len(links) > 5000:
        raise ApplicationError(
            "activation_too_large", "Phase 1 activation supports at most 5000 links", 409
        )
    for typed in definition.link_types:
        group = [link for link in links if link.link_type_id == typed.id]
        for link in group:
            if (link.source_object_type_id, link.target_object_type_id) != (
                typed.source_type,
                typed.target_type,
            ):
                raise ApplicationError(
                    "invalid_link", "Existing link endpoint types differ from schema", 409
                )
        validate_cardinality(typed, group)
    if {link.link_type_id for link in links} - {typed.id for typed in definition.link_types}:
        raise ApplicationError("invalid_link", "Existing links reference a removed link type", 409)
    return links
