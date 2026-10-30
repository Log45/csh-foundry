"""Bounded three-way structural merge. Only declared ID-keyed collections are unordered."""

from typing import cast

from ontology_schema.models import OntologyDefinition
from pydantic import JsonValue

from ontology_platform.branching.contracts import MergeConflict, Resolution, SchemaChange
from ontology_platform.errors import ApplicationError
from ontology_platform.metadata.compatibility import compare

KEYED = {"object_types", "link_types", "action_types", "properties", "parameters"}
MISSING = object()


def pointer(path: tuple[str, ...]) -> str:
    return "/" + "/".join(p.replace("~", "~0").replace("/", "~1") for p in path)


def normalized(definition: OntologyDefinition) -> dict[str, JsonValue]:
    def walk(value: JsonValue, field: str = "") -> JsonValue:
        if isinstance(value, dict):
            return {k: walk(v, k) for k, v in sorted(value.items())}
        if isinstance(value, list):
            items = [walk(v) for v in value]
            if field in KEYED:
                return {str(cast(dict[str, JsonValue], v)["id"]): v for v in items}
            return items
        return value

    return cast(dict[str, JsonValue], walk(definition.model_dump(mode="json")))


def restore(value: JsonValue, field: str = "", reference: JsonValue = None) -> JsonValue:
    if isinstance(value, dict):
        if field in KEYED:
            originals = (
                {str(v["id"]): v for v in reference if isinstance(v, dict) and "id" in v}
                if isinstance(reference, list)
                else {}
            )
            order = [key for key in originals if key in value] + sorted(
                value.keys() - originals.keys()
            )
            return [restore(value[key], reference=originals.get(key)) for key in order]
        original = reference if isinstance(reference, dict) else {}
        return {k: restore(v, k, original.get(k)) for k, v in sorted(value.items())}
    # Ordered action bindings/operations/value arrays retain their original structure and order.
    return value


def changes(previous: OntologyDefinition, proposed: OntologyDefinition) -> list[SchemaChange]:
    result: list[SchemaChange] = []

    def walk(a: object, b: object, path: tuple[str, ...]) -> None:
        if a == b:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(a.keys() | b.keys()):
                walk(a.get(key, MISSING), b.get(key, MISSING), (*path, key))
            return
        result.append(
            SchemaChange(
                path=pointer(path),
                category="added" if a is MISSING else "removed" if b is MISSING else "modified",
                previous=None if a is MISSING else cast(JsonValue, a),
                proposed=None if b is MISSING else cast(JsonValue, b),
            )
        )

    walk(normalized(previous), normalized(proposed), ())
    for change in result:
        parts = [v.replace("~1", "/").replace("~0", "~") for v in change.path.split("/")[1:]]
        group = parts[0]
        updates_old: dict[str, object] = {"object_types": (), "link_types": (), "action_types": ()}
        updates_new = dict(updates_old)
        if group in updates_old and len(parts) >= 2:
            identifier = parts[1]
            change.stable_definition_id = identifier
            old_defs = tuple(v for v in getattr(previous, group) if v.id == identifier)
            new_defs = tuple(v for v in getattr(proposed, group) if v.id == identifier)
            if group == "object_types" and len(parts) >= 4 and parts[2] == "properties":
                change.stable_definition_id += "." + parts[3]
                old_defs = tuple(
                    v.model_copy(
                        update={"properties": tuple(p for p in v.properties if p.id == parts[3])}
                    )
                    for v in old_defs
                )
                new_defs = tuple(
                    v.model_copy(
                        update={"properties": tuple(p for p in v.properties if p.id == parts[3])}
                    )
                    for v in new_defs
                )
            updates_old[group], updates_new[group] = old_defs, new_defs
        # Classification uses the existing conservative classifier on the affected definition slice.
        # These copies are comparison inputs only, never stored as canonical schemas.
        change.compatibility = compare(
            previous.model_copy(update=updates_old), proposed.model_copy(update=updates_new)
        ).classification
    return result


def three_way(
    base: OntologyDefinition,
    target: OntologyDefinition,
    source: OntologyDefinition,
    resolutions: list[Resolution],
) -> tuple[JsonValue, list[MergeConflict]]:
    selected = {r.conflict: r for r in resolutions}
    if len(selected) != len(resolutions):
        raise ApplicationError("invalid_resolution", "Duplicate conflict resolution", 422)
    conflicts: list[MergeConflict] = []
    visited = 0

    def walk(b: object, t: object, s: object, path: tuple[str, ...], depth: int) -> object:
        nonlocal visited
        visited += 1
        if depth > 32 or visited > 20000:
            raise ApplicationError("merge_too_large", "Merge complexity limit exceeded", 422)
        if t == s:
            return t
        if b == t:
            return s
        if b == s:
            return t
        # An independently created same-ID definition is a conflict, even if fields could combine.
        if b is not MISSING and all(isinstance(v, dict) for v in (b, t, s)):
            bd, td, sd = (cast(dict[str, JsonValue], v) for v in (b, t, s))
            result = {}
            for key in sorted(bd.keys() | td.keys() | sd.keys()):
                item = walk(
                    bd.get(key, MISSING),
                    td.get(key, MISSING),
                    sd.get(key, MISSING),
                    (*path, key),
                    depth + 1,
                )
                if item is not MISSING:
                    result[key] = item
            return result
        if len(conflicts) >= 128:
            raise ApplicationError("merge_too_large", "At most 128 merge conflicts", 422)
        key = pointer(path)
        resolution = selected.get(key)
        conflicts.append(
            MergeConflict(
                id=key,
                category="remove_modify"
                if t is MISSING or s is MISSING
                else "identity_reuse"
                if b is MISSING
                else "concurrent_change",
                base=None if b is MISSING else cast(JsonValue, b),
                target=None if t is MISSING else cast(JsonValue, t),
                source=None if s is MISSING else cast(JsonValue, s),
                base_present=b is not MISSING,
                target_present=t is not MISSING,
                source_present=s is not MISSING,
                resolved=resolution is not None,
            )
        )
        if resolution is None or resolution.strategy == "target":
            return t
        if resolution.strategy == "source":
            return s
        return MISSING if resolution.delete else resolution.value

    result = walk(normalized(base), normalized(target), normalized(source), (), 0)
    if selected.keys() - {c.id for c in conflicts}:
        raise ApplicationError(
            "invalid_resolution", "Resolution references an absent conflict", 422
        )
    return restore(cast(JsonValue, result), reference=target.model_dump(mode="json")), conflicts
