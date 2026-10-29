"""Disposable PostgreSQL query measurements; never modifies the operational schema/data.

Run: uv run python scripts/benchmark_queries.py
All generated data passes Phase 1 governed services. This is not a source ingestion pipeline.
"""

import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import Index, Text, event, func, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api/tests"))
from ontology_platform.config import get_settings  # noqa: E402
from ontology_platform.contracts import CreateObject, LinkInput  # noqa: E402
from ontology_platform.db.models import Object  # noqa: E402
from ontology_platform.queries.ast import AggregateRequest, QueryRequest  # noqa: E402
from ontology_platform.queries.service import QueryService  # noqa: E402
from test_phase1 import active, database, make_world  # noqa: E402
from test_queries import load_manufacturing  # noqa: E402

os.environ.setdefault("TEST_DATABASE_URL", get_settings().database_url.get_secret_value())
fixture = database.__wrapped__()
engine, sessions, url = next(fixture)
try:
    world = make_world((engine, sessions, url))
    active(world)
    load_manufacturing(world)
    service = QueryService(sessions, world.registry.authorizer)
    workloads = {
        "status_equality": QueryRequest(
            object_type="Machine",
            filter={"property": "operationalStatus", "operator": "eq", "value": "CRITICAL"},
            select=["machineId"],
            limit=50,
        ),
        "numeric_range": QueryRequest(
            object_type="Machine",
            filter={"property": "temperatureCelsius", "operator": "gt", "value": "900"},
            select=["machineId"],
            limit=50,
        ),
        "numeric_sort": QueryRequest(
            object_type="Machine",
            order_by=[{"property": "temperatureCelsius", "direction": "desc"}],
            select=["machineId"],
            limit=50,
        ),
        "identity_page": QueryRequest(object_type="Machine", select=["machineId"], limit=50),
        "inverse_traversal": QueryRequest(
            object_type="Factory",
            filter={"property": "factoryId", "operator": "eq", "value": "FAC-001"},
            traverse=[{"link": "containsMachine"}],
            select=["machineId"],
            limit=50,
        ),
        "group_count": AggregateRequest(
            object_type="Machine",
            group_by="operationalStatus",
            metrics=[{"name": "count", "operator": "count"}],
        ),
    }
    captured = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            captured.append((statement, parameters))

    def measure():
        result = {}
        for name, request in workloads.items():
            captured.clear()
            event.listen(engine, "before_cursor_execute", capture)
            start = time.perf_counter()
            try:
                response = (
                    service.aggregate if isinstance(request, AggregateRequest) else service.query
                )(world.actor, world.definition.id, request)
            finally:
                event.remove(engine, "before_cursor_execute", capture)
            elapsed = (time.perf_counter() - start) * 1000
            statement, parameters = captured[-1]
            plans = []
            for _ in range(3):
                with engine.connect() as connection:
                    plans.append(
                        connection.exec_driver_sql(
                            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters
                        ).scalar()[0]
                    )
            result[name] = {
                "median_execution_ms": statistics.median(p["Execution Time"] for p in plans),
                "median_planning_ms": statistics.median(p["Planning Time"] for p in plans),
                "application_ms": round(elapsed, 3),
                "plan": plans[-1],
                "result_rows": len(response.groups)
                if isinstance(request, AggregateRequest)
                else len(response.items),
            }
        page = service.query(world.actor, world.definition.id, workloads["identity_page"])
        if page.next_cursor:
            start = time.perf_counter()
            continuation = QueryRequest.model_validate(
                workloads["identity_page"].model_dump(by_alias=True) | {"cursor": page.next_cursor}
            )
            service.query(world.actor, world.definition.id, continuation)
            result["cursor_continuation"] = {
                "application_ms": round((time.perf_counter() - start) * 1000, 3)
            }
        return result

    candidate = next(
        (i for i in Object.__table__.indexes if i.name == "ix_objects_status_lookup"), None
    )
    if candidate is None:
        candidate = Index(
            "ix_objects_status_lookup",
            Object.tenant_id,
            func.md5(Object.ontology_id),
            func.md5(Object.object_type_id),
            func.md5(Object.properties.op("->>", return_type=Text())("operationalStatus")),
        )
    order_candidate = next(
        (i for i in Object.__table__.indexes if i.name == "ix_objects_query_order"), None
    )
    if order_candidate is None:
        order_candidate = Index(
            "ix_objects_query_order",
            Object.tenant_id,
            Object.ontology_id,
            Object.object_type_id,
            Object.object_id.collate("C"),
        )
    order_candidate.drop(engine, checkfirst=True)
    candidate.drop(engine, checkfirst=True)  # Only inside the freshly-created disposable schema.
    with engine.begin() as connection:
        connection.execute(text("ANALYZE objects"))
        connection.execute(text("ANALYZE object_links"))
    baseline_small = measure()
    for batch in range(10):
        world.objects.create_many(
            world.actor,
            world.definition.id,
            [
                CreateObject(
                    object_type_id="Machine",
                    object_id=f"BENCH-{i:05d}",
                    properties={
                        "machineId": f"BENCH-{i:05d}",
                        "machineName": f"Synthetic machine {i}",
                        "operationalStatus": "CRITICAL" if i % 100 == 0 else "RUNNING",
                        "temperatureCelsius": f"{i % 1000}.0",
                    },
                )
                for i in range(batch * 1000, (batch + 1) * 1000)
            ],
        )
    for i in range(300):
        world.objects.create_link(
            world.actor,
            world.definition.id,
            LinkInput(
                link_type_id="locatedInFactory",
                source_object_type_id="Machine",
                source_object_id=f"BENCH-{i:05d}",
                target_object_type_id="Factory",
                target_object_id=f"FAC-{i % 6 + 1:03d}",
            ),
        )
    with engine.begin() as connection:
        connection.execute(text("ANALYZE objects"))
        connection.execute(text("ANALYZE object_links"))
    before = measure()
    candidate.create(engine)
    with engine.begin() as connection:
        connection.execute(text("ANALYZE objects"))
    status_only = measure()
    order_candidate.create(engine)
    with engine.begin() as connection:
        connection.execute(text("ANALYZE objects"))
    after = measure()
    # Measure the existing ontology-wide lock boundary; do not replace it based on a synthetic test.
    blocker = engine.connect()
    transaction = blocker.begin()
    blocker.execute(
        text("SELECT id FROM ontologies WHERE tenant_id=:tenant AND id=:ontology FOR SHARE"),
        {"tenant": world.actor.tenant_id, "ontology": world.definition.id},
    )

    def write_wait():
        start = time.perf_counter()
        world.objects.create(
            world.actor,
            world.definition.id,
            CreateObject(
                object_type_id="Machine",
                object_id="BENCH-CONTENTION",
                properties={
                    "machineId": "BENCH-CONTENTION",
                    "machineName": "Lock probe",
                    "operationalStatus": "RUNNING",
                    "temperatureCelsius": "1.0",
                },
            ),
        )
        return round((time.perf_counter() - start) * 1000, 3)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(write_wait)
        time.sleep(0.1)
        blocked = not future.done()
        transaction.commit()
        blocker.close()
        wait_ms = future.result(timeout=10)
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version()")).scalar()
    output = {
        "dataset": {"fixture_objects": 63, "synthetic_machines": 10000, "forward_links": 370},
        "small_fixture": baseline_small,
        "before_candidate": before,
        "status_lookup_only": status_only,
        "after_candidate": after,
        "lock_probe": {
            "controlled_hold_ms": 100,
            "writer_blocked": blocked,
            "writer_wall_ms": wait_ms,
        },
        "postgres_version": version,
    }
    path = ROOT / "docs/architecture/evidence/phase-2/query-plans.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2) + "\n")
    print("Written", path)
    print(
        "Status equality SQL ms before/after:",
        before["status_equality"]["median_execution_ms"],
        after["status_equality"]["median_execution_ms"],
    )
finally:
    try:
        next(fixture)
    except StopIteration:
        pass
