"""Small reproducible action workload in a disposable migrated PostgreSQL schema."""

import json
import os
import platform
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api/tests"))
from ontology_platform.actions.contracts import ExecuteRequest  # noqa: E402
from ontology_platform.actions.service import ActionExecutionService  # noqa: E402
from ontology_platform.config import get_settings  # noqa: E402
from ontology_platform.db.governance import GovernedService  # noqa: E402
from ontology_platform.errors import ApplicationError  # noqa: E402
from ontology_platform.jobs.webhooks import WebhookRunner  # noqa: E402
from ontology_platform.queries.ast import QueryRequest  # noqa: E402
from ontology_platform.queries.cursor import CursorCodec  # noqa: E402
from ontology_platform.queries.service import QueryService  # noqa: E402
from sqlalchemy import event, text  # noqa: E402
from test_actions import object_row, schedule, task  # noqa: E402
from test_actions import world as action_world  # noqa: E402
from test_phase1 import database  # noqa: E402

os.environ.setdefault("TEST_DATABASE_URL", get_settings().database_url.get_secret_value())
fixture = database.__wrapped__()
engine, sessions, url = next(fixture)
try:
    world = action_world.__wrapped__((engine, sessions, url))
    durations = []

    def begin(session, transaction, connection):
        if transaction.parent is None:
            session.info["measurement_start"] = time.perf_counter()

    def end(session, transaction):
        if transaction.parent is None and "measurement_start" in session.info:
            durations.append((time.perf_counter() - session.info.pop("measurement_start")) * 1000)

    event.listen(sessions, "after_begin", begin)
    event.listen(sessions, "after_transaction_end", end)
    workloads = {}

    def measure(name, function, runs=10):
        samples = []
        outcomes = []
        for index in range(runs):
            start = time.perf_counter()
            outcomes.append(function(index))
            samples.append((time.perf_counter() - start) * 1000)
        workloads[name] = {
            "samples_ms": samples,
            "median_ms": statistics.median(samples),
            "max_ms": max(samples),
            "outcomes": outcomes,
        }

    lock_acquisitions = []

    class MeasuredActions(ActionExecutionService):
        @staticmethod
        def ontology(session, principal, ontology_id, *, write=False):
            started = time.perf_counter()
            row = GovernedService.ontology(session, principal, ontology_id, write=write)
            lock_acquisitions.append((time.perf_counter() - started) * 1000)
            return row

    actions = MeasuredActions(sessions, world.objects.authorizer)
    single_action_transactions = []
    single_action_wall = []

    def update(index):
        revision = object_row(world).version
        action_started = time.perf_counter()
        result = actions.execute(
            world.actor,
            world.definition.id,
            "UpdateMachineStatus",
            ExecuteRequest(
                idempotency_key=f"single-{index}",
                parameters={
                    "machineId": "MCH-001",
                    "newStatus": "STOPPED",
                    "expectedRevision": revision,
                },
            ),
        )
        single_action_wall.append((time.perf_counter() - action_started) * 1000)
        single_action_transactions.append(durations[-1])
        return str(result.execution_id)

    measure("single_object_including_revision_read", update)
    measure(
        "create_task_two_relationships",
        lambda i: str(schedule(world, key=f"schedule-{i}", taskId=f"TASK-BENCH-{i}").execution_id),
    )

    revision = object_row(world).version

    def concurrent(index, same_key):
        try:
            result = actions.execute(
                world.actor,
                world.definition.id,
                "UpdateMachineStatus",
                ExecuteRequest(
                    idempotency_key="concurrent-retry"
                    if same_key
                    else f"concurrent-update-{index}",
                    parameters={
                        "machineId": "MCH-001",
                        "newStatus": "RUNNING",
                        "expectedRevision": revision,
                    },
                ),
            )
            return str(result.execution_id)
        except ApplicationError as exc:
            return exc.code

    for same in (False, True):
        revision = object_row(world).version
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda i, same=same: concurrent(i, same), [0, 1]))
        workloads["concurrent_identical_retries" if same else "concurrent_updates"] = {
            "two_request_wall_ms": (time.perf_counter() - start) * 1000,
            "outcomes": outcomes,
        }

    task(world, key="TASK-ASSIGN")
    measure(
        "relationship_assignment",
        lambda _: str(
            actions.execute(
                world.actor,
                world.definition.id,
                "AssignTask",
                ExecuteRequest(
                    idempotency_key="assign",
                    parameters={
                        "taskId": "TASK-ASSIGN",
                        "employeeId": "EMP-001",
                        "expectedRevision": 1,
                    },
                ),
            ).execution_id
        ),
        runs=1,
    )

    queries = QueryService(sessions, world.objects.authorizer, CursorCodec())
    measure(
        "query_alongside_actions",
        lambda _: len(
            queries.query(
                world.actor, world.definition.id, QueryRequest(object_type="Machine")
            ).items
        ),
        runs=5,
    )
    barrier = Barrier(2)
    revision = object_row(world).version

    def overlap(which):
        barrier.wait(timeout=3)
        started = time.perf_counter()
        if which == "action":
            result = actions.execute(
                world.actor,
                world.definition.id,
                "UpdateMachineStatus",
                ExecuteRequest(
                    idempotency_key="query-overlap",
                    parameters={
                        "machineId": "MCH-001",
                        "newStatus": "RUNNING",
                        "expectedRevision": revision,
                    },
                ),
            )
            outcome = str(result.execution_id)
        else:
            outcome = str(
                len(
                    queries.query(
                        world.actor, world.definition.id, QueryRequest(object_type="Machine")
                    ).items
                )
            )
        return {
            "operation": which,
            "wall_ms": (time.perf_counter() - started) * 1000,
            "outcome": outcome,
        }

    with ThreadPoolExecutor(max_workers=2) as pool:
        workloads["actual_concurrent_query_action"] = {
            "results": list(pool.map(overlap, ["action", "query"]))
        }
    workloads["single_object_action_only"] = {
        "samples_ms": single_action_wall,
        "median_ms": statistics.median(single_action_wall),
        "transaction_samples_ms": single_action_transactions,
        "transaction_median_ms": statistics.median(single_action_transactions),
    }
    held, release = Event(), Event()

    def reader():
        with sessions.begin() as session:
            GovernedService.ontology(session, world.actor, world.definition.id)
            held.set()
            assert release.wait(3)

    with ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(reader)
        assert held.wait(3)
        revision = object_row(world).version  # SHARE reader can overlap this read.
        start = time.perf_counter()
        writing = pool.submit(
            actions.execute,
            world.actor,
            world.definition.id,
            "UpdateMachineStatus",
            ExecuteRequest(
                idempotency_key="overlap",
                parameters={
                    "machineId": "MCH-001",
                    "newStatus": "CRITICAL",
                    "expectedRevision": revision,
                },
            ),
        )
        time.sleep(0.1)
        with engine.connect() as connection:
            waits = [
                dict(row._mapping)
                for row in connection.execute(
                    text("""
                SELECT wait_event_type, wait_event, cardinality(pg_blocking_pids(pid)) AS blockers
                FROM pg_stat_activity WHERE datname=current_database()
                AND wait_event_type='Lock' AND query LIKE '%ontologies%'
                AND EXISTS (SELECT 1 FROM pg_locks AS locks WHERE locks.pid=pg_stat_activity.pid
                    AND locks.relation=to_regclass('ontologies'))
            """)
                )
            ]
        release.set()
        writing.result()
        reading.result()
        workloads["query_shared_lock_action_overlap"] = {
            "writer_wall_ms": (time.perf_counter() - start) * 1000,
            "controlled_hold_ms": 100,
            "lock_acquisition_including_query_ms": lock_acquisitions[-1],
            "observed_lock_waits": waits,
        }
    runner = WebhookRunner(sessions, world.objects.authorizer)
    measure(
        "outbox_claim_no_network_completion",
        lambda _: str(
            runner.run_one(
                world.actor,
                world.definition.id,
                "https://example.org/events",
                transport=lambda *a: 204,
                now=datetime.now(UTC) + timedelta(seconds=1),
            )
        ),
        runs=5,
    )
    with engine.connect() as connection:
        version = connection.scalar(text("SELECT version()"))
        plan = connection.scalar(
            text("""EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            SELECT * FROM action_executions WHERE tenant_id=:tenant AND ontology_id=:ontology
            ORDER BY created_at DESC, id LIMIT 50"""),
            {"tenant": world.actor.tenant_id, "ontology": world.definition.id},
        )
    output = {
        "environment": platform.platform(),
        "postgresql": version,
        "workloads": workloads,
        "transaction_samples_ms": durations,
        "transaction_median_ms": statistics.median(durations),
        "history_plan": plan,
        "limits": (
            "Local small warm-cache samples, 3 initial objects plus 11 tasks. "
            "No production percentiles. Mock transport excludes network latency. "
            "Transactions include measured reads and setup as well as actions."
        ),
    }
    path = ROOT / "docs/architecture/evidence/phase-3/action-benchmarks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: value.get(
                    "median_ms",
                    value.get(
                        "writer_wall_ms", value.get("two_request_wall_ms", value.get("results"))
                    ),
                )
                for key, value in workloads.items()
            },
            indent=2,
        )
    )
finally:
    try:
        next(fixture)
    except StopIteration:
        pass
