"""Reproducible local ingestion measurements in disposable PostgreSQL schemas."""

import json
import os
import platform
import resource
import statistics
import sys
import tempfile
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api/tests"))
from ontology_platform.actions.contracts import ExecuteRequest  # noqa: E402
from ontology_platform.actions.service import ActionExecutionService  # noqa: E402
from ontology_platform.config import get_settings  # noqa: E402
from ontology_platform.db.governance import GovernedService  # noqa: E402
from ontology_platform.ingestion import worker as worker_module  # noqa: E402
from ontology_platform.queries.ast import QueryRequest  # noqa: E402
from ontology_platform.queries.cursor import CursorCodec  # noqa: E402
from ontology_platform.queries.service import QueryService  # noqa: E402
from sqlalchemy import event, text  # noqa: E402
from test_ingestion import setup, submit  # noqa: E402
from test_phase1 import database  # noqa: E402

os.environ.setdefault("TEST_DATABASE_URL", get_settings().database_url.get_secret_value())
fixture = database.__wrapped__()
engine, sessions, url = next(fixture)
results = {}
transactions = []
phase = "setup"
extraction_ms = []
transformation_ms = []
original_extract, original_transform = worker_module.extract, worker_module.transform


def timed_extract(*args):
    start = time.perf_counter()
    try:
        return original_extract(*args)
    finally:
        extraction_ms.append((time.perf_counter() - start) * 1000)


def timed_transform(*args):
    start = time.perf_counter()
    try:
        return original_transform(*args)
    finally:
        transformation_ms.append((time.perf_counter() - start) * 1000)


def began(session, transaction, connection):
    if transaction.parent is None:
        session.info["ingestion_benchmark_start"] = (time.perf_counter(), phase)


def flushed(session, context):
    session.info["ingestion_benchmark_wrote"] = True


def ended(session, transaction):
    if transaction.parent is None:
        started = session.info.pop("ingestion_benchmark_start", None)
        wrote = session.info.pop("ingestion_benchmark_wrote", False)
        if started and wrote:
            transactions.append(
                {"phase": started[1], "ms": (time.perf_counter() - started[0]) * 1000}
            )


def drive(context, run):
    global phase
    world, service, worker = context
    key, token = worker.claim(world.actor, world.definition.id)
    assert key == run.id
    while True:
        phase = service.get(world.actor, world.definition.id, key).phase
        if not worker.step(world.actor, world.definition.id, key, token):
            break
    return service.get(world.actor, world.definition.id, key)


def measure(name, context, *, batch=25, policy="quarantine", mappings=None, retry=False):
    world, service, worker = context
    transactions.clear()
    extraction_ms.clear()
    transformation_ms.clear()
    tracemalloc.reset_peak()
    run = submit(context, policy=policy, size=batch, mappings=mappings)
    started = time.perf_counter()
    if retry:
        key, token = worker.claim(world.actor, world.definition.id)
        worker.step(world.actor, world.definition.id, key, token)
        worker.fail(world.actor, world.definition.id, key, token, "simulated_retry", retryable=True)
    result = drive(context, run)
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    assert result.status == "COMPLETED", result
    results[name] = {
        "rows": result.staged,
        "accepted": result.processed,
        "created": result.created,
        "updated": result.updated,
        "links_created": result.links_created,
        "rejected": result.rejected,
        "attempts": result.attempts,
        "duration_s": elapsed,
        "rows_per_second": result.staged / elapsed,
        "extraction_ms": sum(extraction_ms),
        "transformation_ms": sum(transformation_ms),
        "write_transactions": list(transactions),
        "write_transaction_total_ms": sum(t["ms"] for t in transactions),
        "write_transaction_median_ms": statistics.median(t["ms"] for t in transactions),
        "python_peak_bytes": peak,
    }
    return result


try:
    worker_module.extract, worker_module.transform = timed_extract, timed_transform
    event.listen(sessions, "after_begin", began)
    event.listen(sessions, "after_flush", flushed)
    event.listen(sessions, "after_transaction_end", ended)
    tracemalloc.start()
    with tempfile.TemporaryDirectory(prefix="foundry-ingest-bench-") as directory:
        root = Path(directory)
        contexts = []
        for batch in (10, 25, 100):
            target = root / str(batch)
            target.mkdir()
            context = setup((engine, sessions, url), target)
            measure(f"manufacturing_batch_{batch}", context, batch=batch)
            contexts.append((context, target))
        context, path = contexts[1]
        world, service, worker = context
        measure("unchanged_repeat", context)
        machines = path / "machines.csv"
        machines.write_text(machines.read_text().replace("CNC Mill 01", "Source Updated Mill"))
        measure("changed_source", context)
        actions = ActionExecutionService(sessions, world.objects.authorizer)
        for index in range(1, 11):
            key = f"MCH-{index:03d}"
            revision = world.objects.get(world.actor, world.definition.id, "Machine", key).version
            actions.execute(
                world.actor,
                world.definition.id,
                "UpdateMachineStatus",
                ExecuteRequest(
                    idempotency_key="bench-edit-" + key,
                    parameters={
                        "machineId": key,
                        "newStatus": "MAINTENANCE",
                        "expectedRevision": revision,
                    },
                ),
            )
        machines.write_text(machines.read_text().replace("RUNNING", "STOPPED"))
        measure("reconciliation_heavy", context)
        factories = path / "factories.csv"
        factories.write_text(factories.read_text().replace("FAC-001,North Assembly,", "FAC-001,,"))
        measure("quarantine", context)
        factories.write_bytes((ROOT / "fixtures/factories.csv").read_bytes())
        measure("checkpoint_retry", context, retry=True)

        queries = QueryService(sessions, world.objects.authorizer, CursorCodec())
        run = submit(context, policy="quarantine", size=25)
        key, token = worker.claim(world.actor, world.definition.id)
        while service.get(world.actor, world.definition.id, key).phase != "OBJECTS":
            worker.step(world.actor, world.definition.id, key, token)
        for mode in ("query", "action"):
            barrier = Barrier(2)
            revision = world.objects.get(
                world.actor, world.definition.id, "Machine", "MCH-001"
            ).version

            def concurrent(which, barrier=barrier, revision=revision):
                barrier.wait(timeout=5)
                started = time.perf_counter()
                if which == "ingestion":
                    outcome = worker.step(world.actor, world.definition.id, key, token)
                elif which == "query":
                    outcome = len(
                        queries.query(
                            world.actor, world.definition.id, QueryRequest(object_type="Machine")
                        ).items
                    )
                else:
                    outcome = str(
                        actions.execute(
                            world.actor,
                            world.definition.id,
                            "UpdateMachineStatus",
                            ExecuteRequest(
                                idempotency_key="concurrent-action",
                                parameters={
                                    "machineId": "MCH-001",
                                    "newStatus": "CRITICAL",
                                    "expectedRevision": revision,
                                },
                            ),
                        ).execution_id
                    )
                return {
                    "operation": which,
                    "wall_ms": (time.perf_counter() - started) * 1000,
                    "outcome": outcome,
                }

            with ThreadPoolExecutor(max_workers=2) as pool:
                results[f"concurrent_{mode}"] = list(pool.map(concurrent, ["ingestion", mode]))
        held, release = Event(), Event()

        def reader():
            with sessions.begin() as session:
                GovernedService.ontology(session, world.actor, world.definition.id)
                held.set()
                assert release.wait(5)

        with ThreadPoolExecutor(max_workers=2) as pool:
            reading = pool.submit(reader)
            assert held.wait(5)
            start = time.perf_counter()
            writing = pool.submit(worker.step, world.actor, world.definition.id, key, token)
            time.sleep(0.1)
            with engine.connect() as connection:
                waits = [
                    dict(row._mapping)
                    for row in connection.execute(
                        text("""SELECT wait_event_type,wait_event,
                    cardinality(pg_blocking_pids(pid)) AS blockers FROM pg_stat_activity
                    WHERE datname=current_database() AND wait_event_type='Lock' AND EXISTS
                    (SELECT 1 FROM pg_locks l WHERE l.pid=pg_stat_activity.pid
                    AND l.relation=to_regclass('ontologies'))""")
                    )
                ]
            release.set()
            writing.result()
            reading.result()
            results["controlled_lock_wait"] = {
                "shared_hold_ms": 100,
                "step_wall_ms": (time.perf_counter() - start) * 1000,
                "observed": waits,
            }
        while worker.step(world.actor, world.definition.id, key, token):
            pass
        large_path = root / "synthetic"
        large_path.mkdir()
        large = setup((engine, sessions, url), large_path)
        content = (
            "machineId,machineName,operationalStatus,temperatureCelsius,factoryId\n"
            + "".join(f"SYN-{i:04d},Synthetic {i},RUNNING,25.00,FAC-001\n" for i in range(500))
        )
        (large_path / "machines.csv").write_text(content)
        measure("synthetic_506_objects", large, batch=100, mappings=["Factory", "Machine"])
        measure("synthetic_unchanged", large, batch=50, mappings=["Factory", "Machine"])
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    output = {
        "platform": platform.platform(),
        "results": results,
        "process_peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
        "limits": (
            "Local instrumented samples, not production guarantees. "
            "RSS is whole-process high water including libraries; "
            "tracemalloc excludes native Polars allocations. "
            "Transaction times include governed Python work inside transactions. "
            "Retry uses simulated failure; real process crashes are separate integration tests."
        ),
    }
    destination = ROOT / "docs/architecture/evidence/phase-4/ingestion-benchmarks.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: {
                    x: v[x]
                    for x in (
                        "duration_s",
                        "rows_per_second",
                        "created",
                        "updated",
                        "links_created",
                        "rejected",
                    )
                    if x in v
                }
                if isinstance(v, dict)
                else v
                for k, v in results.items()
            },
            indent=2,
        )
    )
finally:
    worker_module.extract, worker_module.transform = original_extract, original_transform
    try:
        next(fixture)
    except StopIteration:
        pass
