"""Branch/merge acceptance against real PostgreSQL, canonical governance and Phase 7 authority."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from ontology_platform.branching.contracts import (
    BranchCreate,
    BranchEdit,
    DraftHandoff,
    MergeInput,
    Resolution,
)
from ontology_platform.branching.merge import changes, three_way
from ontology_platform.branching.service import BranchService
from ontology_platform.db.models import BranchRevision, Object, SchemaBranch
from ontology_platform.errors import ApplicationError
from ontology_platform.metadata.storage import digest
from ontology_platform.security.contracts import AssignmentInput
from ontology_schema.models import OntologyDefinition
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from test_phase1 import active, client_for, database, make_world, migrate, world  # noqa: F401
from test_security_platform import security  # noqa: F401


def service(w):
    return BranchService(w.sessions, w.registry.authorizer)


def create(w, name):
    return service(w).create(w.actor, w.definition.id, BranchCreate(name=name))


def edited(definition, modify):
    data = definition.model_dump(mode="json")
    modify(data)
    return OntologyDefinition.model_validate(data)


def save(w, branch, modify):
    s = service(w)
    head = s.head(w.actor, w.definition.id, branch.id)
    return s.edit(
        w.actor,
        w.definition.id,
        branch.id,
        BranchEdit(
            expected_revision=head.revision,
            definition=edited(head.definition, modify),
            summary="Test edit",
        ),
    )


def rename(name):
    return lambda d: d.update(name=name)


def test_branch_history_cas_terminal_and_base(world):  # noqa: F811
    w = world
    active(w)
    s = service(w)
    b = create(w, "feature/a")
    assert b.head_hash == digest(w.definition)
    assert s.head(w.actor, w.definition.id, b.id).definition == w.definition
    newer = save(w, b, rename("Development"))
    assert newer.head_revision == 2
    with pytest.raises(ApplicationError, match="revision changed"):
        s.edit(
            w.actor,
            w.definition.id,
            b.id,
            BranchEdit(expected_revision=1, definition=w.definition, summary="stale"),
        )
    assert [r.revision for r in s.history(w.actor, w.definition.id, b.id)] == [2, 1]
    assert w.registry.get(w.actor, w.definition.id).active_version == "1.0.0"
    s.abandon(w.actor, w.definition.id, b.id, 2)
    with pytest.raises(ApplicationError, match="merged or abandoned"):
        save(w, b, rename("closed"))
    with pytest.raises(DBAPIError), w.sessions.begin() as session:
        session.execute(update(BranchRevision).values(summary="tampered"))
    with pytest.raises(DBAPIError), w.sessions.begin() as session:
        session.execute(update(SchemaBranch).values(base_hash="0" * 64))


def test_merge_independent_conflicts_provenance_and_draft(world):  # noqa: F811
    w = world
    active(w)
    s = service(w)
    a, b = create(w, "a"), create(w, "b")
    a = save(
        w,
        a,
        lambda d: d["object_types"][1]["properties"].append(
            {"id": "inspection", "name": "Inspection", "data_type": "boolean"}
        ),
    )
    b = save(w, b, lambda d: d["object_types"][0].update(description="Independent factory edit"))
    request = MergeInput(source_branch=a.id, source_revision=2, target_revision=2)
    preview = s.preview(w.actor, w.definition.id, b.id, request)
    assert not preview.conflicts and not preview.diagnostics
    assert len(s.history(w.actor, w.definition.id, b.id)) == 2
    merged = s.merge(
        w.actor,
        w.definition.id,
        b.id,
        request.model_copy(update={"preview_hash": preview.preview_hash}),
    )
    assert merged.result_revision == 3 and merged.provenance["result_hash"] == digest(
        preview.definition
    )
    assert s.get(w.actor, w.definition.id, a.id).state == "MERGED"
    assert len(s.history(w.actor, w.definition.id, a.id)) == 2
    assert s.merges(w.actor, w.definition.id)[0].id == merged.id
    draft = s.draft(
        w.actor, w.definition.id, b.id, DraftHandoff(expected_revision=3, version="1.1.0")
    )
    assert draft.status == "DRAFT"
    assert w.registry.get(w.actor, w.definition.id).active_version == "1.0.0"
    w.registry.publish(w.actor, w.definition.id, "1.1.0")
    assert w.registry.get(w.actor, w.definition.id).active_version == "1.0.0"
    c, d = create(w, "c"), create(w, "d")
    c, d = save(w, c, rename("Source")), save(w, d, rename("Target"))
    req = MergeInput(source_branch=c.id, source_revision=2, target_revision=2)
    conflict = s.preview(w.actor, w.definition.id, d.id, req)
    assert conflict.conflicts[0].id == "/name" and not conflict.conflicts[0].resolved
    with pytest.raises(ApplicationError, match="Resolve conflicts"):
        s.merge(
            w.actor,
            w.definition.id,
            d.id,
            req.model_copy(update={"preview_hash": conflict.preview_hash}),
        )
    resolved_req = req.model_copy(
        update={"resolutions": [Resolution(conflict="/name", strategy="source")]}
    )
    resolved = s.preview(w.actor, w.definition.id, d.id, resolved_req)
    assert resolved.definition.name == "Source"
    s.merge(
        w.actor,
        w.definition.id,
        d.id,
        resolved_req.model_copy(update={"preview_hash": resolved.preview_hash}),
    )


def test_stale_preview_concurrent_writers_and_rollback(world):  # noqa: F811
    w = world
    active(w)
    s = service(w)
    a, b = create(w, "a"), create(w, "b")
    req = MergeInput(source_branch=a.id, source_revision=1, target_revision=1)
    preview = s.preview(w.actor, w.definition.id, b.id, req)
    save(w, a, rename("new"))
    with pytest.raises(ApplicationError, match="revision changed"):
        s.merge(
            w.actor,
            w.definition.id,
            b.id,
            req.model_copy(update={"preview_hash": preview.preview_hash}),
        )

    def attempt(name):
        try:
            s.edit(
                w.actor,
                w.definition.id,
                b.id,
                BranchEdit(
                    expected_revision=1,
                    definition=edited(w.definition, rename(name)),
                    summary="racing",
                ),
            )
            return "ok"
        except ApplicationError as e:
            return e.code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(attempt, ["one", "two"])) == ["branch_changed", "ok"]

    class LateDeny:
        def __init__(self):
            self.calls = 0

        def require(self, principal, operation, resource):
            self.calls += 1
            if self.calls > 1:
                raise ApplicationError("forbidden", "Late denial", 403)

    before = s.head(w.actor, w.definition.id, b.id)
    with pytest.raises(ApplicationError, match="Late denial"):
        BranchService(w.sessions, LateDeny()).edit(
            w.actor,
            w.definition.id,
            b.id,
            BranchEdit(expected_revision=2, definition=w.definition, summary="rolled back"),
        )
    assert s.head(w.actor, w.definition.id, b.id) == before


def test_branch_tenant_api_constraints_and_migration(world, database):  # noqa: F811
    w = world
    active(w)
    b = create(w, "a")
    other = make_world(database)
    active(other)
    with pytest.raises(ApplicationError, match="not found"):
        service(other).get(other.actor, other.definition.id, b.id)
    with pytest.raises(IntegrityError), w.sessions.begin() as session:
        session.add(
            BranchRevision(
                tenant_id=other.actor.tenant_id,
                ontology_id=w.definition.id,
                branch_id=b.id,
                revision=2,
                parent_revision=1,
                content_hash=b.head_hash,
                definition_json=w.definition.canonical_json(),
                author="x",
                summary="x",
                provenance={},
            )
        )
    with client_for(w) as client:
        base = f"/api/v1/ontologies/{w.definition.id}/branches"
        assert client.get(base).json()[0]["id"] == str(b.id)
        assert client.post(base, json={"name": "a"}).status_code == 409
        assert client.post(base + f"/{b.id}/edit", json={}).status_code == 422
        assert client.post(base, content=b" " * 65537).status_code == 413
    migrate(w.engine, "0013_security", downgrade=True)
    migrate(w.engine)
    with w.sessions() as session:
        assert session.scalar(select(Object).limit(1)) is None
    assert w.registry.get(w.actor, w.definition.id).active_version == "1.0.0"


def test_phase7_branch_permissions_revocation(security):  # noqa: F811
    w, auth, administration, admin, reader, _ = security
    s = BranchService(w.sessions, auth)
    with pytest.raises(ApplicationError):
        s.create(reader, w.definition.id, BranchCreate(name="denied"))
    administration.assign(
        admin, AssignmentInput(principal_id=reader.principal_id, role_id="ontology-editor")
    )
    b = s.create(reader, w.definition.id, BranchCreate(name="allowed"))
    administration.assign(
        admin,
        AssignmentInput(principal_id=reader.principal_id, role_id="ontology-editor"),
        revoke=True,
    )
    with pytest.raises(ApplicationError):
        s.abandon(reader, w.definition.id, b.id, 1)
    assert s.get(admin, w.definition.id, b.id).state == "ACTIVE"


@pytest.mark.parametrize("kind", ["type", "remove", "link", "action", "primary", "null", "default"])
def test_three_way_conflict_taxonomy(kind):
    import json
    from pathlib import Path

    base = OntologyDefinition.model_validate_json(
        Path("ontologies/examples/manufacturing.json").read_text()
    )
    a, b = deepcopy(base.model_dump(mode="json")), deepcopy(base.model_dump(mode="json"))
    if kind == "type":
        a["object_types"][1]["properties"][1]["data_type"] = "json"
        b["object_types"][1]["properties"][1]["data_type"] = "boolean"
    elif kind == "remove":
        a["object_types"][1]["properties"].pop(1)
        b["object_types"][1]["properties"][1]["name"] = "Changed"
    elif kind == "link":
        a["link_types"][0]["target_type"] = "Employee"
        b["link_types"][0]["target_type"] = "MaintenanceTask"
    elif kind == "action":
        actions = json.loads(Path("ontologies/examples/manufacturing-actions.json").read_text())
        # Operations are ordered, atomic declarations.
        a["action_types"] = actions
        b["action_types"] = deepcopy(actions)
        b["action_types"][0]["name"] = "Another declaration"
    elif kind == "primary":
        for data in (a, b):
            for prop in data["object_types"][0]["properties"]:
                prop["required"] = True
        a["object_types"][0]["primary_key"] = "factoryName"
        b["object_types"][0]["primary_key"] = "location"
    elif kind == "null":
        # Remove versus nullability change is a structural conflict.
        a["object_types"][1]["properties"].pop(1)
        b["object_types"][1]["properties"][1]["nullable"] = True
    else:
        for data, default in ((a, "a"), (b, "b")):
            data["object_types"][1]["properties"][1]["default"] = default
    ours, theirs = OntologyDefinition.model_validate(a), OntologyDefinition.model_validate(b)
    _, conflicts = three_way(base, ours, theirs, [])
    assert conflicts
    resolved, conflicts = three_way(
        base, ours, theirs, [Resolution(conflict=c.id, strategy="source") for c in conflicts]
    )
    assert all(c.resolved for c in conflicts)
    OntologyDefinition.model_validate(resolved)
    assert changes(base, ours) == changes(base, ours)


def test_invalid_combined_references_manual_resolution_and_merge_rollback(world):  # noqa: F811
    w = world
    active(w)
    s = service(w)
    a, b = create(w, "remove"), create(w, "new-link")
    # Removing Employee also removes its referencing link; both branches independently validate.
    a = save(
        w,
        a,
        lambda d: d.update(
            object_types=[o for o in d["object_types"] if o["id"] != "Employee"],
            link_types=[link for link in d["link_types"] if link["target_type"] != "Employee"],
        ),
    )
    b = save(
        w,
        b,
        lambda d: d["link_types"].append(
            {
                "id": "newEmployeeLink",
                "name": "New employee",
                "source_type": "Machine",
                "target_type": "Employee",
                "cardinality": "many_to_many",
            }
        ),
    )
    req = MergeInput(source_branch=a.id, source_revision=2, target_revision=2)
    preview = s.preview(w.actor, w.definition.id, b.id, req)
    assert preview.definition is None and preview.diagnostics
    assert preview.conflicts[-1].id == "/$schema"
    req = req.model_copy(
        update={"resolutions": [Resolution(conflict="/$schema", strategy="target")]}
    )
    preview = s.preview(w.actor, w.definition.id, b.id, req)
    assert not preview.diagnostics and preview.definition is not None

    class LateDeny:
        def __init__(self):
            self.calls = 0

        def require(self, principal, operation, resource):
            self.calls += 1
            if self.calls > 1:
                raise ApplicationError("forbidden", "Merge revoked", 403)

    with pytest.raises(ApplicationError, match="Merge revoked"):
        BranchService(w.sessions, LateDeny()).merge(
            w.actor,
            w.definition.id,
            b.id,
            req.model_copy(update={"preview_hash": preview.preview_hash}),
        )
    assert s.get(w.actor, w.definition.id, a.id).state == "ACTIVE"
    assert s.get(w.actor, w.definition.id, b.id).head_revision == 2
    assert s.merges(w.actor, w.definition.id) == []


def test_two_concurrent_merges_cannot_overwrite(world):  # noqa: F811
    w = world
    active(w)
    s = service(w)
    a, b, target = create(w, "a"), create(w, "b"), create(w, "target")

    def prepared(source):
        request = MergeInput(source_branch=source.id, source_revision=1, target_revision=1)
        preview = s.preview(w.actor, w.definition.id, target.id, request)
        return request.model_copy(update={"preview_hash": preview.preview_hash})

    requests = [prepared(a), prepared(b)]

    def attempt(request):
        try:
            s.merge(w.actor, w.definition.id, target.id, request)
            return "ok"
        except ApplicationError as exc:
            return exc.code

    with ThreadPoolExecutor(2) as executor:
        assert sorted(executor.map(attempt, requests)) == ["branch_changed", "ok"]
    assert len(s.merges(w.actor, w.definition.id)) == 1


def test_merge_preserves_definition_order_and_rejects_unknown_resolutions():
    import json
    from pathlib import Path

    from ontology_platform.metadata.compatibility import compare

    data = json.loads(Path("ontologies/examples/manufacturing.json").read_text())
    data["action_types"] = json.loads(
        Path("ontologies/examples/manufacturing-actions.json").read_text()
    )
    base = OntologyDefinition.model_validate(data)
    result, conflicts = three_way(base, base, base, [])
    assert OntologyDefinition.model_validate(result).canonical_json() == base.canonical_json()
    assert not conflicts
    assert compare(base, OntologyDefinition.model_validate(result)).classification == "additive"
    with pytest.raises(ApplicationError, match="absent conflict"):
        three_way(base, base, base, [Resolution(conflict="/name", strategy="source")])


def test_breaking_merge_requires_existing_migration_guards_at_publication(world):  # noqa: F811
    from ontology_platform.contracts import PlanInput

    w = world
    active(w)
    s = service(w)
    source, target = create(w, "breaking"), create(w, "target")
    source = save(w, source, lambda d: d["object_types"][0]["properties"].pop())
    req = MergeInput(source_branch=source.id, source_revision=2, target_revision=1)
    preview = s.preview(w.actor, w.definition.id, target.id, req)
    assert preview.migration_required
    s.merge(
        w.actor,
        w.definition.id,
        target.id,
        req.model_copy(update={"preview_hash": preview.preview_hash}),
    )
    s.draft(w.actor, w.definition.id, target.id, DraftHandoff(expected_revision=2, version="2.0.0"))
    with pytest.raises(ApplicationError, match="approved plan"):
        w.registry.publish(w.actor, w.definition.id, "2.0.0")
    plan = w.registry.create_plan(w.actor, w.definition.id, "2.0.0", PlanInput())
    w.registry.approve_plan(w.actor, w.definition.id, plan.id)
    w.registry.publish(w.actor, w.definition.id, "2.0.0", plan.id)
    assert w.registry.get(w.actor, w.definition.id).active_version == "1.0.0"
