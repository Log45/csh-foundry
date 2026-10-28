"""Conservative schema compatibility: uncertain changes require a migration plan."""

from ontology_schema.models import ActionTypeDefinition, LinkTypeDefinition, OntologyDefinition

from ontology_platform.contracts import Compatibility


def compare(previous: OntologyDefinition | None, proposed: OntologyDefinition) -> Compatibility:
    reasons: list[str] = []
    if previous is None:
        return Compatibility(classification="additive", reasons=[])
    if (previous.id, previous.tenant_id, previous.namespace) != (
        proposed.id,
        proposed.tenant_id,
        proposed.namespace,
    ):
        reasons.append("Ontology identity or namespace changed")
    new_objects = {o.id: o for o in proposed.object_types}
    for old in previous.object_types:
        new = new_objects.get(old.id)
        if new is None:
            reasons.append(f"Object type removed: {old.id}")
            continue
        if new.primary_key != old.primary_key:
            reasons.append(f"Primary key changed: {old.id}")
        old_properties = {p.id: p for p in old.properties}
        new_properties = {p.id: p for p in new.properties}
        for prop_id, prop in old_properties.items():
            other = new_properties.get(prop_id)
            if other is None:
                reasons.append(f"Property removed: {old.id}.{prop_id}")
            elif prop.model_dump(exclude={"name", "indexed"}) != other.model_dump(
                exclude={"name", "indexed"}
            ):
                reasons.append(f"Property constraints/type changed: {old.id}.{prop_id}")
        for prop in new.properties:
            if prop.id not in old_properties and prop.required:
                reasons.append(f"Required property added: {old.id}.{prop.id}")
    groups: list[
        tuple[
            str,
            tuple[LinkTypeDefinition, ...] | tuple[ActionTypeDefinition, ...],
            tuple[LinkTypeDefinition, ...] | tuple[ActionTypeDefinition, ...],
        ]
    ] = [
        ("Link", previous.link_types, proposed.link_types),
        ("Action", previous.action_types, proposed.action_types),
    ]
    for label, old_defs, new_defs in groups:
        proposed_by_id = {d.id: d.model_dump(exclude={"name"}) for d in new_defs}
        for definition in old_defs:
            if proposed_by_id.get(definition.id) != definition.model_dump(exclude={"name"}):
                reasons.append(f"{label} removed or changed: {definition.id}")
    return Compatibility(classification="breaking" if reasons else "additive", reasons=reasons)
