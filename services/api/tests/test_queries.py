"""Phase 2 integration on the same real, isolated PostgreSQL fixture as Phase 1."""

import csv
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ontology_platform.contracts import CreateObject, LinkInput, ObjectPatch
from ontology_platform.errors import ApplicationError
from ontology_platform.main import create_app
from ontology_platform.queries.ast import AggregateRequest, Predicate, QueryRequest
from ontology_platform.queries.cursor import CursorCodec
from ontology_platform.queries.object_set import ObjectSet
from ontology_platform.queries.service import QueryService
from ontology_platform.security.query import QueryGrant
from ontology_schema.models import OntologyDefinition
from test_phase1 import active, make_world, next_definition
from test_phase1 import database as pg_database

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.integration


def load_manufacturing(world):
    d, p = world.definition, world.actor
    tables = {}
    records = []
    for file, kind, key in [
        ("factories.csv", "Factory", "factoryId"),
        ("machines.csv", "Machine", "machineId"),
        ("employees.csv", "Employee", "employeeId"),
        ("maintenance_tasks.csv", "MaintenanceTask", "taskId"),
    ]:
        with (ROOT / "fixtures" / file).open(newline="") as stream:
            tables[kind] = list(csv.DictReader(stream))
        names = {prop.id for t in d.object_types if t.id == kind for prop in t.properties}
        records.extend(
            CreateObject(
                object_type_id=kind,
                object_id=row[key],
                properties={name: row[name] for name in names},
            )
            for row in tables[kind]
        )
    world.objects.create_many(p, d.id, records)
    for row in tables["Machine"]:
        world.objects.create_link(
            p,
            d.id,
            LinkInput(
                link_type_id="locatedInFactory",
                source_object_type_id="Machine",
                source_object_id=row["machineId"],
                target_object_type_id="Factory",
                target_object_id=row["factoryId"],
            ),
        )
    for row in tables["MaintenanceTask"]:
        for link, kind, column in [
            ("taskForMachine", "Machine", "machineId"),
            ("assignedEmployee", "Employee", "assignedEmployeeId"),
        ]:
            world.objects.create_link(
                p,
                d.id,
                LinkInput(
                    link_type_id=link,
                    source_object_type_id="MaintenanceTask",
                    source_object_id=row["taskId"],
                    target_object_type_id=kind,
                    target_object_id=row[column],
                ),
            )
    return tables


@pytest.fixture
def database():
    yield from pg_database.__wrapped__()


@pytest.fixture
def query_world(database):
    world = make_world(database)
    active(world)
    load_manufacturing(world)
    return world


def query_service(world, policy=None, codec=None):
    return QueryService(world.sessions, policy or world.registry.authorizer, codec)


def query(world, **kwargs):
    return query_service(world).query(
        world.actor,
        world.definition.id,
        QueryRequest.model_validate({"object_type": "Machine"} | kwargs),
    )


def ids(page):
    return [item.object_id for item in page.items]


def test_manufacturing_filters_boolean_and_projection(query_world):
    w = query_world
    page = query(
        w,
        filter={
            "and": [
                {"property": "operationalStatus", "operator": "eq", "value": "RUNNING"},
                {"property": "temperatureCelsius", "operator": "gt", "value": "80"},
            ]
        },
        select=["machineId", "machineName"],
        order_by=[{"property": "temperatureCelsius", "direction": "desc"}],
    )
    assert ids(page) == ["MCH-007", "MCH-019"]
    assert set(page.items[0].properties) == {"machineId", "machineName"}
    assert page.items[0].tenant_id == w.actor.tenant_id
    assert ids(
        query(
            w,
            filter={
                "or": [
                    {"property": "operationalStatus", "operator": "eq", "value": "CRITICAL"},
                    {"property": "machineId", "operator": "eq", "value": "MCH-001"},
                ]
            },
        )
    ) == ["MCH-001", "MCH-005", "MCH-011", "MCH-017"]
    assert (
        len(
            query(
                w,
                filter={
                    "not": {"property": "operationalStatus", "operator": "eq", "value": "CRITICAL"}
                },
            ).items
        )
        == 17
    )


@pytest.mark.parametrize(
    "operator,value,expected",
    [
        ("eq", "73.90", ["MCH-001"]),
        ("ne", "73.9", None),
        ("gt", "90", ["MCH-007"]),
        ("gte", "93.6", ["MCH-007"]),
        ("lt", "25", ["MCH-020"]),
        ("lte", "24.5", ["MCH-020"]),
    ],
)
def test_numeric_operators(query_world, operator, value, expected):
    page = query(
        query_world, filter={"property": "temperatureCelsius", "operator": operator, "value": value}
    )
    assert ids(page) == expected if expected is not None else len(page.items) == 19


@pytest.mark.parametrize(
    "operator,value", [("contains", "CNC"), ("starts_with", "CNC"), ("ends_with", "01")]
)
def test_string_matching(query_world, operator, value):
    page = query(
        query_world, filter={"property": "machineName", "operator": operator, "value": value}
    )
    assert "MCH-001" in ids(page)
    assert (
        query(
            query_world, filter={"property": "machineName", "operator": "contains", "value": "%"}
        ).items
        == []
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"filter": {"property": "missing", "operator": "eq", "value": "x"}},
        {"filter": {"property": "temperatureCelsius", "operator": "gt", "value": 80}},
        {"filter": {"property": "temperatureCelsius", "operator": "contains", "value": "8"}},
        {"filter": {"property": "machineName", "operator": "gt", "value": "abc"}},
        {"select": ["missing"]},
        {"order_by": [{"property": "missing"}]},
        {
            "filter": {
                "property": "machineId'; DROP TABLE objects;--",
                "operator": "eq",
                "value": "x",
            }
        },
    ],
)
def test_schema_rejections(query_world, payload):
    with pytest.raises(ApplicationError) as caught:
        query(query_world, **payload)
    assert caught.value.status_code == 422


def test_cursor_continuation_ties_and_incompatibility(query_world):
    w = query_world
    service = query_service(w)
    request = QueryRequest(
        object_type="Machine", order_by=[{"property": "operationalStatus"}], limit=3
    )
    seen = []
    page = service.query(w.actor, w.definition.id, request)
    first_cursor = page.next_cursor
    while True:
        seen += ids(page)
        if not page.next_cursor:
            break
        page = service.query(
            w.actor,
            w.definition.id,
            QueryRequest.model_validate(
                request.model_dump(by_alias=True) | {"cursor": page.next_cursor}
            ),
        )
    assert len(seen) == len(set(seen)) == 20
    assert seen[:3] == ["MCH-005", "MCH-011", "MCH-017"]
    for changes in [
        {"limit": 2},
        {"select": ["machineId"]},
        {"order_by": []},
        {"filter": {"property": "machineId", "operator": "eq", "value": "MCH-001"}},
    ]:
        with pytest.raises(ApplicationError) as caught:
            service.query(
                w.actor,
                w.definition.id,
                QueryRequest.model_validate(
                    request.model_dump(by_alias=True) | changes | {"cursor": first_cursor}
                ),
            )
        assert caught.value.code == "invalid_cursor"
    with pytest.raises(ApplicationError):
        service.query(
            w.actor, w.definition.id, QueryRequest(object_type="Machine", cursor="garbage")
        )
    assert ids(
        query(w, order_by=[{"property": "temperatureCelsius", "direction": "asc"}], limit=2)
    ) == ["MCH-020", "MCH-002"]
    assert ids(
        query(w, order_by=[{"property": "temperatureCelsius", "direction": "desc"}], limit=2)
    ) == ["MCH-007", "MCH-019"]


def test_cursor_schema_and_concurrent_changes(query_world):
    w = query_world
    service = query_service(w)
    request = QueryRequest(object_type="Machine", limit=2)
    page = service.query(w.actor, w.definition.id, request)
    # Non-anchor updates are visible; pagination is not a historical snapshot.
    w.objects.patch(
        w.actor,
        w.definition.id,
        "Machine",
        "MCH-003",
        ObjectPatch(expected_version=1, properties={"machineName": "modified"}),
    )
    continuation = QueryRequest.model_validate(
        request.model_dump(by_alias=True) | {"cursor": page.next_cursor}
    )
    assert (
        service.query(w.actor, w.definition.id, continuation).items[0].properties["machineName"]
        == "modified"
    )
    w.objects.patch(
        w.actor,
        w.definition.id,
        "Machine",
        "MCH-002",
        ObjectPatch(expected_version=1, properties={"machineName": "anchor changed"}),
    )
    with pytest.raises(ApplicationError) as caught:
        service.query(w.actor, w.definition.id, continuation)
    assert caught.value.code == "cursor_stale"
    current = service.query(w.actor, w.definition.id, request)
    proposed = next_definition(w, lambda data: None, "1.1.0")
    w.registry.draft(w.actor, w.definition.id, proposed)
    w.registry.publish(w.actor, w.definition.id, proposed.version)
    w.registry.activate(w.actor, w.definition.id, proposed.version)
    with pytest.raises(ApplicationError) as caught:
        service.query(
            w.actor,
            w.definition.id,
            QueryRequest.model_validate(
                request.model_dump(by_alias=True) | {"cursor": current.next_cursor}
            ),
        )
    assert caught.value.code == "cursor_schema_changed"


def test_traversal_and_aggregations(query_world):
    w = query_world
    request = {
        "object_type": "Factory",
        "filter": {"property": "factoryId", "operator": "eq", "value": "FAC-001"},
        "traverse": [
            {"link": "containsMachine"},
            {"link": "hasMaintenanceTask"},
            {"link": "assignedEmployee"},
        ],
    }
    page = query_service(w).query(w.actor, w.definition.id, QueryRequest.model_validate(request))
    assert page.object_type == "Employee" and len(page.items) > 0
    tasks = AggregateRequest.model_validate(
        {
            **request,
            "traverse": request["traverse"][:2],
            "metrics": [{"name": "count", "operator": "count"}],
        }
    )
    count = query_service(w).aggregate(w.actor, w.definition.id, tasks)
    with (ROOT / "fixtures/machines.csv").open() as stream:
        members = {r["machineId"] for r in csv.DictReader(stream) if r["factoryId"] == "FAC-001"}
    with (ROOT / "fixtures/maintenance_tasks.csv").open() as stream:
        expected = sum(r["machineId"] in members for r in csv.DictReader(stream))
    assert expected == 6
    assert count.groups[0].values["count"].value == expected
    result = query_service(w).aggregate(
        w.actor,
        w.definition.id,
        AggregateRequest(
            object_type="Machine",
            metrics=[
                {"name": "count", "operator": "count"},
                {"name": "sum", "operator": "sum", "property": "temperatureCelsius"},
                {"name": "avg", "operator": "avg", "property": "temperatureCelsius"},
                {"name": "min", "operator": "min", "property": "temperatureCelsius"},
                {"name": "max", "operator": "max", "property": "temperatureCelsius"},
            ],
        ),
    )
    with (ROOT / "fixtures/machines.csv").open() as stream:
        temperatures = [Decimal(r["temperatureCelsius"]) for r in csv.DictReader(stream)]
    values = result.groups[0].values
    assert values["count"].value == 20
    assert Decimal(values["sum"].value) == sum(temperatures)
    assert Decimal(values["avg"].value) == sum(temperatures) / len(temperatures)
    assert Decimal(values["max"].value) == max(temperatures)
    assert Decimal(values["min"].value) == min(temperatures)
    groups = query_service(w).aggregate(
        w.actor,
        w.definition.id,
        AggregateRequest(
            object_type="Machine",
            metrics=[{"name": "n", "operator": "count"}],
            group_by="operationalStatus",
        ),
    )
    assert {g.key.value: g.values["n"].value for g in groups.groups} == {
        "CRITICAL": 3,
        "MAINTENANCE": 3,
        "RUNNING": 11,
        "STOPPED": 3,
    }


class RestrictedPolicy:
    def __init__(self, world):
        self.original = world.registry.authorizer
        self.machine_ids = ("MCH-001", "MCH-005")
        self.visible = ("machineId", "machineName", "operationalStatus")
        self.block_intermediate = False

    def require(self, principal, operation, resource):
        self.original.require(principal, operation, resource)

    def query_grant(self, principal, ontology_id, object_type):
        self.original.query_grant(principal, ontology_id, object_type)
        if object_type == "Machine":
            return QueryGrant(
                allowed_object_ids=() if self.block_intermediate else self.machine_ids,
                visible_properties=self.visible,
                revision="policy-v1",
            )
        return QueryGrant(revision="policy-v1")


def test_policy_projection_filter_sort_count_aggregate_and_traversal(query_world):
    w = query_world
    policy = RestrictedPolicy(w)
    service = query_service(w, policy)
    page = service.query(w.actor, w.definition.id, QueryRequest(object_type="Machine"))
    assert ids(page) == ["MCH-001", "MCH-005"]
    assert "temperatureCelsius" not in page.items[0].properties
    for request in [
        QueryRequest(object_type="Machine", select=["temperatureCelsius"]),
        QueryRequest(object_type="Machine", order_by=[{"property": "temperatureCelsius"}]),
        QueryRequest(
            object_type="Machine",
            filter=Predicate(property="temperatureCelsius", operator="gt", value="0"),
        ),
    ]:
        with pytest.raises(ApplicationError) as caught:
            service.query(w.actor, w.definition.id, request)
        assert caught.value.status_code == 403
    assert (
        service.aggregate(
            w.actor,
            w.definition.id,
            AggregateRequest(object_type="Machine", metrics=[{"name": "n", "operator": "count"}]),
        )
        .groups[0]
        .values["n"]
        .value
        == 2
    )
    with pytest.raises(ApplicationError):
        service.aggregate(
            w.actor,
            w.definition.id,
            AggregateRequest(
                object_type="Machine",
                metrics=[{"name": "avg", "operator": "avg", "property": "temperatureCelsius"}],
            ),
        )
    root = QueryRequest(
        object_type="Factory",
        traverse=[{"link": "containsMachine"}, {"link": "hasMaintenanceTask"}],
    )
    assert len(service.query(w.actor, w.definition.id, root).items) == 3
    policy.block_intermediate = True
    assert service.query(w.actor, w.definition.id, root).items == []


def test_policy_cursor_and_cross_tenant_reuse(query_world, database):
    w = query_world
    policy = RestrictedPolicy(w)
    codec = CursorCodec()
    service = query_service(w, policy, codec)
    request = QueryRequest(object_type="Machine", limit=1)
    cursor = service.query(w.actor, w.definition.id, request).next_cursor
    policy.machine_ids = ("MCH-005",)
    with pytest.raises(ApplicationError) as caught:
        service.query(
            w.actor, w.definition.id, QueryRequest(object_type="Machine", limit=1, cursor=cursor)
        )
    assert caught.value.code == "invalid_cursor"
    other = make_world(database)
    active(other)
    with pytest.raises(ApplicationError):
        query_service(other, codec=codec).query(
            other.actor,
            other.definition.id,
            QueryRequest(object_type="Machine", limit=1, cursor=cursor),
        )
    assert query_service(other).query(other.actor, other.definition.id, request).items == []


def test_object_sets_and_http(query_world):
    w = query_world
    service = query_service(w)
    original = ObjectSet.objects(service, w.actor, w.definition.id, "Machine")
    subset = (
        original.filter(operationalStatus="RUNNING")
        .filter(temperatureCelsius__gt="80")
        .order_by("temperatureCelsius", descending=True)
        .select("machineId")
        .limit(1)
    )
    assert original.request.filter is None
    first = subset.execute()
    assert ids(first) == ["MCH-007"]
    assert ids(subset.after(first.next_cursor).execute()) == ["MCH-019"]
    app = create_app(w.settings)
    app.state.sessions = w.sessions
    with TestClient(app) as client:
        base = f"/api/v1/ontologies/{w.definition.id}"
        result = client.post(
            base + "/objects/Machine/query",
            json=subset.request.model_dump(mode="json", by_alias=True),
        )
        assert result.status_code == 200, result.text
        assert result.json()["items"][0]["object_id"] == "MCH-007"
        assert (
            client.post(
                base + "/objects/Factory/query", json={"object_type": "Machine"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                base + "/aggregate",
                json={"object_type": "Machine", "metrics": [{"name": "n", "operator": "count"}]},
            ).json()["groups"][0]["values"]["n"]["value"]
            == 20
        )
        assert (
            client.post(
                base + "/traverse",
                json={"object_type": "Factory", "traverse": [{"link": "containsMachine"}]},
            ).status_code
            == 200
        )


@pytest.fixture
def typed_world(database):
    w = make_world(database)
    data = w.definition.model_dump(mode="json")
    props = [{"id": "id", "name": "ID", "data_type": "string", "required": True}]
    for name, kind in [
        ("i", "integer"),
        ("f", "float"),
        ("d", "decimal"),
        ("b", "boolean"),
        ("day", "date"),
        ("ts", "timestamp"),
        ("u", "uuid"),
        ("j", "json"),
        ("a", "integer"),
        ("note", "string"),
        ("optionalNumber", "decimal"),
    ]:
        prop = {"id": name, "name": name, "data_type": kind, "nullable": True}
        if kind == "decimal":
            prop.update(precision=12, scale=2)
        if name == "a":
            prop["array"] = True
        props.append(prop)
    data["object_types"].append(
        {"id": "Probe", "name": "Probe", "primary_key": "id", "properties": props}
    )
    data["object_types"].append(
        {
            "id": "Noise",
            "name": "Noise",
            "primary_key": "id",
            "properties": [
                {"id": name, "name": name, "data_type": "string", "required": True}
                for name in ("id", "d", "ts", "day", "u", "b")
            ],
        }
    )
    w.definition = OntologyDefinition.model_validate(data)
    active(w)
    records = []
    for i in range(1, 4):
        properties = {
            "id": f"P{i}",
            "i": i,
            "f": float(i),
            "d": "1.00" if i == 1 else "2.50",
            "b": i > 1,
            "day": f"2026-01-0{i}",
            "ts": "2026-01-01T12:00:00Z" if i != 2 else "2026-01-01T07:00:00-05:00",
            "u": f"00000000-0000-0000-0000-{i:012d}",
            "j": {"n": i},
            "a": [1, 2] if i == 1 else [2, 1],
        }
        if i == 1:
            properties.update(note=None, optionalNumber=None)
        if i == 3:
            properties.update(note="present", optionalNumber="3.25")
        records.append(
            CreateObject(object_type_id="Probe", object_id=f"P{i}", properties=properties)
        )
    records.append(
        CreateObject(
            object_type_id="Noise",
            object_id="N",
            properties={
                "id": "N",
                "d": "bad numeric",
                "ts": "bad timestamp",
                "day": "bad date",
                "u": "bad uuid",
                "b": "bad bool",
            },
        )
    )
    w.objects.create_many(w.actor, w.definition.id, records)
    return w


@pytest.mark.parametrize(
    "prop,value,expected",
    [
        ("i", 2, ["P2"]),
        ("f", 2.0, ["P2"]),
        ("d", "1.0", ["P1"]),
        ("b", True, ["P2", "P3"]),
        ("day", "2026-01-02", ["P2"]),
        ("ts", "2026-01-01T12:00:00+00:00", ["P1", "P2", "P3"]),
        ("u", "00000000-0000-0000-0000-000000000002", ["P2"]),
        ("j", {"n": 2}, ["P2"]),
        ("a", [1, 2], ["P1"]),
    ],
)
def test_canonical_types_and_safe_mixed_type_casts(typed_world, prop, value, expected):
    result = query_service(typed_world).query(
        typed_world.actor,
        typed_world.definition.id,
        QueryRequest(
            object_type="Probe", filter=Predicate(property=prop, operator="eq", value=value)
        ),
    )
    assert ids(result) == expected


def test_null_missing_projection_sorting_and_not(typed_world):
    w = typed_world
    service = query_service(w)

    def run(**kwargs):
        return service.query(w.actor, w.definition.id, QueryRequest(object_type="Probe", **kwargs))

    assert ids(run(filter={"property": "note", "operator": "is_null"})) == ["P1", "P2"]
    assert ids(run(filter={"property": "note", "operator": "is_not_null"})) == ["P3"]
    assert ids(run(filter={"property": "note", "operator": "ne", "value": "other"})) == ["P3"]
    assert ids(run(filter={"not": {"property": "note", "operator": "eq", "value": "present"}})) == [
        "P1",
        "P2",
    ]
    projected = run(select=["id", "note"])
    assert projected.items[0].properties["note"] is None
    assert "note" not in projected.items[1].properties
    for direction in ["asc", "desc"]:
        request = QueryRequest(
            object_type="Probe",
            order_by=[{"property": "optionalNumber", "direction": direction}],
            limit=1,
        )
        seen = []
        page = service.query(w.actor, w.definition.id, request)
        while True:
            seen += ids(page)
            if not page.next_cursor:
                break
            page = service.query(
                w.actor,
                w.definition.id,
                QueryRequest.model_validate(
                    request.model_dump(by_alias=True) | {"cursor": page.next_cursor}
                ),
            )
        assert seen == ["P3", "P1", "P2"]  # NULLS LAST, then identity tie-break.
    uuid_page = run(order_by=[{"property": "u", "direction": "desc"}], limit=1)
    assert ids(uuid_page) == ["P3"]
    assert ids(
        run(
            order_by=[{"property": "u", "direction": "desc"}], limit=1, cursor=uuid_page.next_cursor
        )
    ) == ["P2"]


def test_null_grouping_empty_aggregates_and_group_bound(typed_world):
    w = typed_world
    service = query_service(w)
    result = service.aggregate(
        w.actor,
        w.definition.id,
        AggregateRequest(
            object_type="Probe",
            group_by="note",
            metrics=[
                {"name": "n", "operator": "count"},
                {"name": "present", "operator": "count", "property": "note"},
            ],
        ),
    )
    assert [
        (g.key.value, g.values["n"].value, g.values["present"].value) for g in result.groups
    ] == [("present", 1, 1), (None, 2, 0)]
    with pytest.raises(ApplicationError) as caught:
        service.aggregate(
            w.actor,
            w.definition.id,
            AggregateRequest(
                object_type="Probe",
                group_by="i",
                max_groups=2,
                metrics=[{"name": "n", "operator": "count"}],
            ),
        )
    assert caught.value.code == "aggregation_too_large"
    empty = service.aggregate(
        w.actor,
        w.definition.id,
        AggregateRequest(
            object_type="Probe",
            filter=Predicate(property="id", operator="eq", value="absent"),
            metrics=[
                {"name": "n", "operator": "count"},
                {"name": "sum", "operator": "sum", "property": "i"},
                {"name": "avg", "operator": "avg", "property": "i"},
            ],
        ),
    )
    assert empty.groups[0].values["n"].value == 0
    assert (
        empty.groups[0].values["sum"].value is None and empty.groups[0].values["avg"].value is None
    )
    for metric in [
        {"name": "x", "operator": "sum", "property": "b"},
        {"name": "x", "operator": "min", "property": "a"},
        {"name": "x", "operator": "max", "property": "u"},
    ]:
        with pytest.raises(ApplicationError):
            service.aggregate(
                w.actor, w.definition.id, AggregateRequest(object_type="Probe", metrics=[metric])
            )


def test_cyclic_paths_and_unauthorized_links(query_world):
    w = query_world
    request = QueryRequest(
        object_type="Machine",
        filter=Predicate(property="machineId", operator="eq", value="MCH-001"),
        traverse=[
            {"link": "locatedInFactory"},
            {"link": "containsMachine"},
            {"link": "locatedInFactory"},
            {"link": "containsMachine"},
        ],
    )
    assert ids(query_service(w).query(w.actor, w.definition.id, request)) == [
        "MCH-001",
        "MCH-007",
        "MCH-013",
        "MCH-019",
    ]

    class NoLinks(RestrictedPolicy):
        def require(self, principal, operation, resource):
            super().require(principal, operation, resource)
            if operation == "link:read":
                raise ApplicationError("forbidden", "Link denied", 403)

    with pytest.raises(ApplicationError):
        query_service(w, NoLinks(w)).query(w.actor, w.definition.id, request)
    with pytest.raises(ApplicationError):
        query(w, traverse=[{"link": "assignedEmployee"}])


def test_hidden_policy_predicates_and_legacy_authorizer_fail_closed(query_world):
    w = query_world

    class HiddenPredicate(RestrictedPolicy):
        def query_grant(self, principal, ontology_id, object_type):
            self.original.query_grant(principal, ontology_id, object_type)
            if object_type == "Machine":
                return QueryGrant(
                    visible_properties=("machineId",),
                    revision="v1",
                    filter=Predicate(property="temperatureCelsius", operator="gt", value="80"),
                )
            return QueryGrant(revision="v1")

    assert ids(
        query_service(w, HiddenPredicate(w)).query(
            w.actor, w.definition.id, QueryRequest(object_type="Machine")
        )
    ) == ["MCH-005", "MCH-007", "MCH-019"]

    class Legacy:
        def require(self, principal, operation, resource):
            return None

    with pytest.raises(ApplicationError) as caught:
        query_service(w, Legacy()).query(
            w.actor, w.definition.id, QueryRequest(object_type="Machine")
        )
    assert caught.value.code == "query_policy_required"


def test_filtered_intermediate_sets_and_builder_use_same_ast(query_world):
    from ontology_platform.queries.ast import Metric

    w = query_world
    service = query_service(w)
    objects = (
        ObjectSet.objects(service, w.actor, w.definition.id, "Factory")
        .filter(factoryId="FAC-005")
        .traverse("containsMachine")
        .filter(operationalStatus="CRITICAL")
        .filter(temperatureCelsius__gt="0")
        .traverse("hasMaintenanceTask")
    )
    assert ids(objects.execute()) == ["TASK-011", "TASK-013", "TASK-015"]
    assert objects.aggregate(Metric(name="n", operator="count")).groups[0].values["n"].value == 3
    direct = service.query(
        w.actor,
        w.definition.id,
        QueryRequest.model_validate(objects.request.model_dump(by_alias=True)),
    )
    assert ids(direct) == ids(objects.execute())


def test_literal_injection_values_and_cursor_property_hiding(query_world):
    import base64

    w = query_world
    assert (
        query(
            w,
            filter={
                "property": "machineName",
                "operator": "eq",
                "value": "' OR 1=1; DROP TABLE objects; --",
            },
        ).items
        == []
    )
    page = query(w, order_by=[{"property": "temperatureCelsius"}], select=["machineId"], limit=1)
    raw = base64.urlsafe_b64decode(page.next_cursor + "=" * (-len(page.next_cursor) % 4))[:-32]
    assert b"temperatureCelsius" not in raw
    assert b"values_hash" in raw and b"24.5" not in raw


def test_http_query_errors_denials_and_policy_aggregates(query_world):
    w = query_world
    app = create_app(w.settings)
    app.state.sessions = w.sessions
    app.state.authorizer = RestrictedPolicy(w)
    with TestClient(app) as client:
        path = f"/api/v1/ontologies/{w.definition.id}"
        hidden = client.post(
            path + "/objects/Machine/query",
            json={"object_type": "Machine", "select": ["temperatureCelsius"]},
        )
        assert hidden.status_code == 403 and hidden.json()["error"]["code"] == "property_forbidden"
        assert (
            client.post(
                path + "/objects/Machine/query", json={"object_type": "Machine", "limit": 100000}
            ).status_code
            == 422
        )
        invalid = client.post(
            path + "/objects/Machine/query",
            json={
                "object_type": "Machine",
                "filter": {"property": "unknown", "operator": "eq", "value": "x"},
            },
        )
        assert invalid.status_code == 422
        assert (
            client.post(
                path + "/aggregate",
                json={
                    "object_type": "Machine",
                    "group_by": "temperatureCelsius",
                    "metrics": [{"name": "n", "operator": "count"}],
                },
            ).status_code
            == 403
        )
    disabled = w.settings.model_copy(update={"trusted_local_identity": False})
    app = create_app(disabled)
    app.state.sessions = w.sessions
    with TestClient(app) as client:
        assert (
            client.post(
                f"/api/v1/ontologies/{w.definition.id}/objects/Machine/query",
                json={"object_type": "Machine"},
            ).status_code
            == 401
        )


def test_safe_status_index_with_large_future_property_values(database):
    w = make_world(database)
    data = w.definition.model_dump(mode="json")
    data["object_types"].append(
        {
            "id": "LargeStatus",
            "name": "Large status",
            "primary_key": "id",
            "properties": [
                {"id": "id", "name": "ID", "data_type": "string", "required": True},
                {
                    "id": "operationalStatus",
                    "name": "Status",
                    "data_type": "string",
                    "required": True,
                },
            ],
        }
    )
    w.definition = OntologyDefinition.model_validate(data)
    active(w)
    value = "long status value " * 200
    w.objects.create(
        w.actor,
        w.definition.id,
        CreateObject(
            object_type_id="LargeStatus",
            object_id="big",
            properties={"id": "big", "operationalStatus": value},
        ),
    )
    result = query_service(w).query(
        w.actor,
        w.definition.id,
        QueryRequest(
            object_type="LargeStatus",
            filter=Predicate(property="operationalStatus", operator="eq", value=value),
        ),
    )
    assert ids(result) == ["big"]


def test_cross_tenant_queries_joins_and_aggregates_with_overlapping_ids(query_world, database):
    w = query_world
    other = make_world(database)
    active(other)
    other.objects.create_many(
        other.actor,
        other.definition.id,
        [
            CreateObject(
                object_type_id="Factory",
                object_id="FAC-001",
                properties={
                    "factoryId": "FAC-001",
                    "factoryName": "Other tenant",
                    "location": "Private",
                },
            ),
            CreateObject(
                object_type_id="Machine",
                object_id="ONLY-B",
                properties={
                    "machineId": "ONLY-B",
                    "machineName": "Private",
                    "operationalStatus": "CRITICAL",
                    "temperatureCelsius": "999.0",
                },
            ),
        ],
    )
    other.objects.create_link(
        other.actor,
        other.definition.id,
        LinkInput(
            link_type_id="locatedInFactory",
            source_object_type_id="Machine",
            source_object_id="ONLY-B",
            target_object_type_id="Factory",
            target_object_id="FAC-001",
        ),
    )
    path = QueryRequest(
        object_type="Factory",
        filter=Predicate(property="factoryId", operator="eq", value="FAC-001"),
        traverse=[{"link": "containsMachine"}],
    )
    assert "ONLY-B" not in ids(query_service(w).query(w.actor, w.definition.id, path))
    assert ids(query_service(other).query(other.actor, other.definition.id, path)) == ["ONLY-B"]
    result = query_service(w).aggregate(
        w.actor,
        w.definition.id,
        AggregateRequest(
            object_type="Machine",
            metrics=[
                {"name": "n", "operator": "count"},
                {"name": "max", "operator": "max", "property": "temperatureCelsius"},
            ],
        ),
    )
    assert result.groups[0].values["n"].value == 20
    assert Decimal(result.groups[0].values["max"].value) == Decimal("93.6")


def test_group_counts_and_final_target_authorization(query_world):
    w = query_world
    policy = RestrictedPolicy(w)
    service = query_service(w, policy)
    result = service.aggregate(
        w.actor,
        w.definition.id,
        AggregateRequest(
            object_type="Machine",
            group_by="operationalStatus",
            metrics=[{"name": "n", "operator": "count"}],
        ),
    )
    assert {g.key.value: g.values["n"].value for g in result.groups} == {
        "RUNNING": 1,
        "CRITICAL": 1,
    }

    class NoEmployees(RestrictedPolicy):
        def query_grant(self, principal, ontology_id, object_type):
            if object_type == "Employee":
                return QueryGrant(revision="no-employees", allowed_object_ids=())
            return super().query_grant(principal, ontology_id, object_type)

    path = QueryRequest(
        object_type="Factory",
        traverse=[
            {"link": "containsMachine"},
            {"link": "hasMaintenanceTask"},
            {"link": "assignedEmployee"},
        ],
    )
    assert query_service(w, NoEmployees(w)).query(w.actor, w.definition.id, path).items == []


def test_explicit_offset_pages_and_object_sets(query_world):
    w = query_world
    service = query_service(w)
    page = service.query(
        w.actor, w.definition.id, QueryRequest(object_type="Machine", limit=2, pagination="offset")
    )
    assert ids(page) == ["MCH-001", "MCH-002"] and page.has_more and page.next_cursor is None
    second = (
        ObjectSet.objects(service, w.actor, w.definition.id, "Machine").limit(2).offset(2).execute()
    )
    assert ids(second) == ["MCH-003", "MCH-004"] and second.next_cursor is None


def test_order_index_migration_drift_is_not_hidden(database):
    from alembic import command
    from alembic.config import Config
    from alembic.util.exc import AutogenerateDiffsDetected
    from ontology_platform.db.models import Object
    from sqlalchemy import text

    engine, _, _ = database
    config = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.check(config)
        connection.execute(text("DROP INDEX ix_objects_query_order"))
        connection.execute(
            text(
                "CREATE INDEX ix_objects_query_order ON objects "
                "(tenant_id, ontology_id, object_type_id, object_id)"
            )
        )
        with pytest.raises(AutogenerateDiffsDetected):
            command.check(config)
        connection.execute(text("DROP INDEX ix_objects_query_order"))
        next(i for i in Object.__table__.indexes if i.name == "ix_objects_query_order").create(
            connection
        )
        command.check(config)
