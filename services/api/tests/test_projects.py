"""Phase 11 acceptance on isolated real PostgreSQL schemas and existing security services."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from ontology_platform.db.models import AuthorizationAudit, Folder, Object, Resource, Version
from ontology_platform.errors import ApplicationError
from ontology_platform.projects.contracts import (
    CatalogImport,
    CreateFolder,
    CreateProject,
    CreateResource,
    MemberChange,
    ShareChange,
    UpdateFolder,
    UpdateResource,
)
from ontology_platform.projects.service import ProjectService
from ontology_platform.security.contracts import AssignmentInput, RoleInput
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from test_phase1 import active, client_for, database, make_world, migrate, world  # noqa: F401
from test_security_platform import restrict, security  # noqa: F401


def svc(w, auth=None):
    return ProjectService(w.sessions, auth or w.registry.authorizer)


def project(s, actor, name="Project A"):
    return s.create_project(actor, CreateProject(name=name))


def resource(s, actor, project_id, **kwargs):
    return s.create_resource(
        actor,
        project_id,
        CreateResource.model_validate(
            {
                "resource_type": "ONTOLOGY_OBJECT_TYPE",
                "ontology_id": "manufacturing",
                "schema_version": "1.0.0",
                "entity_id": "Machine",
                "name": "Machines",
                **kwargs,
            }
        ),
    )


def raises(code, call):
    with pytest.raises(ApplicationError) as exc:
        call()
    assert exc.value.status_code == code


def test_projects_folders_identity_constraints_archive(world):  # noqa: F811
    w = world
    active(w)
    s = svc(w)
    a, b = project(s, w.actor), project(s, w.actor, "Project B")
    assert [r.id for r in s.list_projects(w.actor, 1, 1)] == [b.id]
    root = s.create_folder(w.actor, a.id, CreateFolder(name="root"))
    child = s.create_folder(w.actor, a.id, CreateFolder(name="child", parent_id=root.id))
    assert s.folders(w.actor, a.id, root.id)[0].id == child.id
    renamed = s.update_folder(
        w.actor, a.id, child.id, UpdateFolder(name="renamed", expected_revision=1), 1
    )
    assert renamed.id == child.id and renamed.parent_id is None
    assert s.get_folder(w.actor, a.id, child.id) == renamed
    raises(
        412,
        lambda: s.update_folder(
            w.actor, a.id, child.id, UpdateFolder(name="stale", expected_revision=1), 1
        ),
    )
    raises(409, lambda: s.create_folder(w.actor, a.id, CreateFolder(name="root")))
    raises(
        404, lambda: s.create_folder(w.actor, b.id, CreateFolder(name="invalid", parent_id=root.id))
    )
    sub = s.create_folder(w.actor, a.id, CreateFolder(name="sub", parent_id=root.id))
    raises(
        409,
        lambda: s.update_folder(
            w.actor,
            a.id,
            root.id,
            UpdateFolder(name="root", parent_id=sub.id, expected_revision=1),
            1,
        ),
    )
    raises(
        409,
        lambda: s.update_folder(
            w.actor,
            a.id,
            root.id,
            UpdateFolder(name="root", parent_id=root.id, expected_revision=1),
            1,
        ),
    )
    raises(409, lambda: s.update_folder(w.actor, a.id, root.id, None, 1))
    r = resource(s, w.actor, a.id, folder_id=root.id)
    updated = s.update_resource(
        w.actor,
        r.id,
        UpdateResource(name="Renamed machines", folder_id=child.id, expected_revision=1),
        1,
    )
    assert updated.id == r.id
    assert s.get_resource(w.actor, r.id).folder_id == child.id
    raises(
        404,
        lambda: s.update_resource(
            w.actor, r.id, UpdateResource(name="invalid", folder_id=uuid4(), expected_revision=2), 2
        ),
    )
    assert s.resources(w.actor, a.id, child.id, "Renamed")[0].id == r.id
    assert s.resources(w.actor, a.id, child.id, "%") == []  # Literal search, no wildcard expansion.
    archived = s.update_project(w.actor, a.id, None, a.revision)
    assert archived.state == "ARCHIVED" and s.get_project(w.actor, a.id).state == "ARCHIVED"
    raises(409, lambda: s.create_folder(w.actor, a.id, CreateFolder(name="no")))
    raises(404, lambda: s.get_resource(w.actor, r.id))
    with w.sessions() as db:
        assert db.get(Resource, (w.actor.tenant_id, r.id)) is not None
        assert db.scalar(select(func.count()).select_from(Version)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuthorizationAudit)
                .where(AuthorizationAudit.category == "project")
            )
            >= 8
        )


def grant_projects(admin_service, admin, reader):
    admin_service.role(
        admin,
        RoleInput(
            id="project-user",
            permissions=("project:read", "project:create", "project:write", "project:manage"),
        ),
    )
    admin_service.assign(
        admin, AssignmentInput(principal_id=reader.principal_id, role_id="project-user")
    )


def test_explicit_membership_shares_revocation_and_cumulative_policies(security):  # noqa: F811
    w, auth, admin_service, admin, reader, objects = security
    s = svc(w, auth)
    grant_projects(admin_service, admin, reader)
    a, b = project(s, admin), project(s, admin, "B")
    private = resource(s, admin, a.id)
    assert s.list_projects(reader) == []
    for key in [a.id, uuid4()]:
        raises(404, lambda key=key: s.get_project(reader, key))
    raises(404, lambda: s.get_resource(reader, private.id))
    b = s.member(
        admin,
        b.id,
        MemberChange(principal_id=reader.principal_id, role="viewer", expected_revision=b.revision),
    )
    raises(403, lambda: s.create_folder(reader, b.id, CreateFolder(name="no")))
    raises(
        403,
        lambda: s.member(
            reader,
            b.id,
            MemberChange(principal_id=admin.principal_id, role=None, expected_revision=b.revision),
        ),
    )
    raises(
        409,
        lambda: s.member(
            admin,
            a.id,
            MemberChange(principal_id=admin.principal_id, role=None, expected_revision=a.revision),
        ),
    )
    assert s.resources(reader, b.id, shared=True) == []
    private = s.share(
        admin,
        private.id,
        ShareChange(project_id=b.id, enabled=True, expected_revision=private.revision),
    )
    assert s.resources(reader, b.id, shared=True)[0].id == private.id
    assert s.get_resource(reader, private.id).id == private.id
    raises(
        404,
        lambda: s.update_resource(
            reader,
            private.id,
            UpdateResource(name="no", expected_revision=private.revision),
            private.revision,
        ),
    )
    restrict(admin_service, admin, principal_id=reader.principal_id)
    # Project discovery never grants operational/property/action authority.
    assert objects.count(reader, "manufacturing", "Factory") == 1
    assert "location" not in objects.get(reader, "manufacturing", "Factory", "F1").properties
    raises(403, lambda: auth.require(reader, "action:invoke", f"{reader.tenant_id}/manufacturing"))
    private = s.share(
        admin,
        private.id,
        ShareChange(project_id=b.id, enabled=False, expected_revision=private.revision),
    )
    assert s.resources(reader, b.id, shared=True) == []
    raises(404, lambda: s.get_resource(reader, private.id))
    # No global private-registration collision oracle: same canonical entity, independent reference.
    own = project(s, reader, "Reader owned")
    alias = resource(s, reader, own.id)
    assert alias.id != private.id
    # Transfer ownership explicitly, then remove old owner; membership changes use Project CAS.
    a = s.member(
        admin,
        a.id,
        MemberChange(principal_id=reader.principal_id, role="owner", expected_revision=a.revision),
    )
    a = s.member(
        reader,
        a.id,
        MemberChange(principal_id=admin.principal_id, role=None, expected_revision=a.revision),
    )
    raises(404, lambda: s.get_project(admin, a.id))
    assert s.get_project(reader, a.id).role == "owner"


def test_catalog_idempotency_and_canonical_compatibility(world):  # noqa: F811
    w = world
    active(w)
    s = svc(w)
    a = project(s, w.actor)
    body = CatalogImport(ontology_id="manufacturing", schema_version="1.0.0")
    first = s.import_catalog(w.actor, a.id, body)
    second = s.import_catalog(w.actor, a.id, body)
    assert first and [r.id for r in first] == [r.id for r in second]
    assert {r.resource_type for r in first} >= {
        "ONTOLOGY_OBJECT_TYPE",
        "ONTOLOGY_LINK_TYPE",
        "ONTOLOGY_VERSION",
    }
    assert w.registry.get(w.actor, "manufacturing").active_version == "1.0.0"
    raises(404, lambda: resource(s, w.actor, a.id, entity_id="missing"))
    archived = s.update_resource(w.actor, first[0].id, None, first[0].revision)
    assert archived.state == "ARCHIVED"
    raises(404, lambda: s.get_resource(w.actor, archived.id))


def test_cross_tenant_api_validation_and_database_integrity(world, database):  # noqa: F811
    w = world
    active(w)
    s = svc(w)
    a = project(s, w.actor)
    r = resource(s, w.actor, a.id)
    other = make_world(database)
    other_s = svc(other)
    assert other_s.list_projects(other.actor) == []
    raises(404, lambda: other_s.get_project(other.actor, a.id))
    raises(404, lambda: other_s.get_resource(other.actor, r.id))
    b = project(other_s, other.actor, "Other")
    raises(
        404,
        lambda: s.share(
            w.actor, r.id, ShareChange(project_id=b.id, enabled=True, expected_revision=1)
        ),
    )
    raises(404, lambda: resource(other_s, other.actor, b.id))
    with pytest.raises(IntegrityError), w.sessions.begin() as db:
        db.add(
            Folder(
                tenant_id=other.actor.tenant_id,
                project_id=a.id,
                id=uuid4(),
                name="x",
                created_by="x",
                updated_by="x",
            )
        )
    with client_for(w) as client:
        assert client.get("/api/v1/projects?limit=101").status_code == 422
        assert client.get("/api/v1/projects?offset=-1").status_code == 422
        assert client.get(f"/api/v1/resources/{r.id}").status_code == 200
        assert client.post("/api/v1/projects", json={"name": "../invalid"}).status_code == 422
        assert (
            client.post(
                f"/api/v1/projects/{a.id}/resources",
                json={"resource_type": "DATASET", "name": "no"},
            ).status_code
            == 422
        )
    with pytest.raises(ValidationError):
        CreateFolder(name=" ")


def test_conflicting_mutations_and_maximum_depth(world):  # noqa: F811
    s, p = svc(world), world.actor
    a = project(s, p)
    f = s.create_folder(p, a.id, CreateFolder(name="one"))

    def rename(name):
        try:
            return s.update_folder(
                p, a.id, f.id, UpdateFolder(name=name, expected_revision=1), 1
            ).name
        except ApplicationError as error:
            return error.status_code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(rename, ["first", "second"]))
    assert 412 in results and len([r for r in results if isinstance(r, str)]) == 1
    current = f.id
    for depth in range(31):
        current = s.create_folder(p, a.id, CreateFolder(name=f"d{depth}", parent_id=current)).id
    raises(409, lambda: s.create_folder(p, a.id, CreateFolder(name="too deep", parent_id=current)))
    raises(409, lambda: s.update_folder(p, a.id, f.id, None, 2))


def test_upgrade_existing_data_and_historical_security_roles(database):  # noqa: F811
    engine, sessions, _ = database
    # Empty Phase 11 rollback is permitted; populated rollback fails closed.
    migrate(engine, "0017_capacity", downgrade=True)
    w = make_world(database)
    active(w)
    from ontology_platform.db.models import (
        Membership,
        PlatformPrincipal,
        Role,
        RoleAssignment,
        SecurityState,
    )
    from test_phase1 import factory

    w.objects.create(w.actor, "manufacturing", factory())
    with sessions.begin() as db:
        db.add(PlatformPrincipal(id="historical-admin", principal_type="user", enabled=True))
        if db.get(SecurityState, w.actor.tenant_id) is None:
            db.add(SecurityState(tenant_id=w.actor.tenant_id))
        db.flush()
        db.add(
            Membership(
                tenant_id=w.actor.tenant_id,
                principal_id="historical-admin",
                enabled=True,
                attributes={},
            )
        )
        db.add(
            Role(
                tenant_id=w.actor.tenant_id,
                id="tenant-administrator",
                permissions=["tenant:read", "schema:read"],
            )
        )
        db.flush()
        db.add(
            RoleAssignment(
                tenant_id=w.actor.tenant_id,
                principal_id="historical-admin",
                role_id="tenant-administrator",
            )
        )
    with sessions() as db:
        before = db.scalar(select(Version.definition_json))
    migrate(engine)
    with sessions() as db:
        assert db.scalar(select(Version.definition_json)) == before
        assert db.scalar(select(func.count()).select_from(Resource)) == 0
        assert db.scalar(select(func.count()).select_from(Object)) == 1
        assert db.get(Role, (w.actor.tenant_id, "tenant-administrator")).permissions == [
            "tenant:read",
            "schema:read",
        ]
        assert (
            db.get(
                RoleAssignment,
                (w.actor.tenant_id, "historical-admin", "phase11-project-administrator"),
            )
            is not None
        )
    s = svc(w)
    project(s, w.actor)
    with pytest.raises(RuntimeError, match="forward-only"):
        migrate(engine, "0017_capacity", downgrade=True)


def test_ontology_permission_required_after_project_access(security):  # noqa: F811
    from datetime import UTC, datetime, timedelta

    from ontology_platform.security.contracts import IdentityInput
    from ontology_platform.security.identity import resolve
    from test_security_platform import ISSUER

    w, auth, admin_service, admin, _, _ = security
    s = svc(w, auth)
    who = admin_service.identity(admin, IdentityInput(issuer=ISSUER, subject="project-only"))
    admin_service.role(admin, RoleInput(id="project-only", permissions=("project:read",)))
    admin_service.assign(admin, AssignmentInput(principal_id=who, role_id="project-only"))
    reader = resolve(
        w.sessions,
        ISSUER,
        "project-only",
        w.actor.tenant_id,
        method="oidc",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    a = project(s, admin)
    r = resource(s, admin, a.id)
    s.member(admin, a.id, MemberChange(principal_id=who, role="viewer", expected_revision=1))
    assert s.get_project(reader, a.id).role == "viewer"
    raises(403, lambda: s.resources(reader, a.id))
    raises(403, lambda: s.get_resource(reader, r.id))


def test_share_archive_and_concurrent_revocation(security):  # noqa: F811
    from threading import Event

    w, auth, admin_service, admin, reader, _ = security
    s = svc(w, auth)
    grant_projects(admin_service, admin, reader)
    a, b = project(s, admin), project(s, admin, "B")
    b = s.member(
        admin,
        b.id,
        MemberChange(principal_id=reader.principal_id, role="viewer", expected_revision=1),
    )
    r = resource(s, admin, a.id)
    r = s.share(admin, r.id, ShareChange(project_id=b.id, enabled=True, expected_revision=1))
    entered, release = Event(), Event()

    def reading():
        with s.scope(reader) as db:
            assert s.resource(db, reader, r.id).id == r.id
            entered.set()
            assert release.wait(5)

    with ThreadPoolExecutor(2) as pool:
        read = pool.submit(reading)
        assert entered.wait(5)
        revoke = pool.submit(
            s.share,
            admin,
            r.id,
            ShareChange(project_id=b.id, enabled=False, expected_revision=r.revision),
        )
        assert not revoke.done()
        release.set()
        read.result()
        r = revoke.result()
    raises(404, lambda: s.get_resource(reader, r.id))
    r = s.share(
        admin, r.id, ShareChange(project_id=b.id, enabled=True, expected_revision=r.revision)
    )
    s.update_project(admin, a.id, None, a.revision)
    assert s.resources(reader, b.id, shared=True) == []
    raises(404, lambda: s.get_resource(reader, r.id))


def test_published_action_adapter_and_database_authority(world):  # noqa: F811
    import json
    from pathlib import Path

    from ontology_schema.models import OntologyDefinition
    from sqlalchemy import update

    w = world
    data = w.definition.model_dump(mode="json")
    data["action_types"] = json.loads(
        Path("ontologies/examples/manufacturing-actions.json").read_text()
    )
    w.definition = OntologyDefinition.model_validate(data)
    active(w)
    s = svc(w)
    a = project(s, w.actor)
    r = resource(s, w.actor, a.id, resource_type="ONTOLOGY_ACTION", entity_id="UpdateMachineStatus")
    assert r.entity_id == "UpdateMachineStatus"
    with pytest.raises(IntegrityError), w.sessions.begin() as db:
        db.execute(update(Resource).where(Resource.id == r.id).values(entity_id="missing"))
    # Canonical publication remains immutable; registry renames only change the presentation.
    renamed = s.update_resource(
        w.actor, r.id, UpdateResource(name="Status", expected_revision=1), 1
    )
    assert renamed.entity_id == r.entity_id
    assert (
        w.registry.version(w.actor, "manufacturing", "1.0.0").definition.action_types[0].id
        == "UpdateMachineStatus"
    )


def test_disabled_owner_is_not_an_ownership_transfer_target(security):  # noqa: F811
    from ontology_platform.security.contracts import MembershipInput

    w, auth, administration, admin, reader, _ = security
    s = svc(w, auth)
    grant_projects(administration, admin, reader)
    a = project(s, admin)
    a = s.member(
        admin,
        a.id,
        MemberChange(principal_id=reader.principal_id, role="owner", expected_revision=1),
    )
    administration.member(admin, reader.principal_id, MembershipInput(enabled=False))
    raises(
        409,
        lambda: s.member(
            admin,
            a.id,
            MemberChange(principal_id=admin.principal_id, role=None, expected_revision=a.revision),
        ),
    )

    # Removing the disabled owner is safe: the current enabled owner remains.
    s.member(
        admin,
        a.id,
        MemberChange(principal_id=reader.principal_id, role=None, expected_revision=a.revision),
    )
    assert [m.principal_id for m in s.members(admin, a.id)] == [admin.principal_id]


def test_owner_transfer_requires_live_platform_management_authority(security):  # noqa: F811
    w, auth, administration, admin, reader, _ = security
    s = svc(w, auth)
    a = project(s, admin)
    raises(
        409,
        lambda: s.member(
            admin,
            a.id,
            MemberChange(principal_id=reader.principal_id, role="owner", expected_revision=1),
        ),
    )
    grant_projects(administration, admin, reader)
    a = s.member(
        admin,
        a.id,
        MemberChange(principal_id=reader.principal_id, role="owner", expected_revision=1),
    )
    administration.assign(
        admin,
        AssignmentInput(principal_id=reader.principal_id, role_id="project-user"),
        revoke=True,
    )
    raises(
        409,
        lambda: s.member(
            admin,
            a.id,
            MemberChange(principal_id=admin.principal_id, role=None, expected_revision=a.revision),
        ),
    )


def test_concurrent_opposing_folder_moves_cannot_form_cycle(world):  # noqa: F811
    s, p = svc(world), world.actor
    a = project(s, p)
    left = s.create_folder(p, a.id, CreateFolder(name="left"))
    right = s.create_folder(p, a.id, CreateFolder(name="right"))

    def move(pair):
        source, target = pair
        try:
            s.update_folder(
                p,
                a.id,
                source.id,
                UpdateFolder(name=source.name, parent_id=target.id, expected_revision=1),
                1,
            )
            return 200
        except ApplicationError as error:
            return error.status_code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(move, [(left, right), (right, left)])) == [200, 409]
