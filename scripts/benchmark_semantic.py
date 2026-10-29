"""Bounded private-schema measurements; no production performance claim."""

import json
import os
import resource
import sys
import tempfile
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api/tests"))
from ontology_platform.actions.contracts import ExecuteRequest  # noqa: E402
from ontology_platform.actions.service import ActionExecutionService  # noqa: E402
from ontology_platform.config import get_settings  # noqa: E402
from ontology_platform.contracts import CreateObject  # noqa: E402
from ontology_platform.queries.ast import QueryRequest  # noqa: E402
from ontology_platform.queries.service import QueryService  # noqa: E402
from ontology_platform.semantic.contracts import CompileInput, ExportInput, JobInput  # noqa: E402
from ontology_platform.semantic.engine import OpenOntologiesAdapter  # noqa: E402
from ontology_platform.semantic.service import SemanticService  # noqa: E402
from ontology_platform.semantic.worker import SemanticWorker  # noqa: E402
from test_ingestion import setup, submit  # noqa: E402
from test_phase1 import database  # noqa: E402

os.environ.setdefault("TEST_DATABASE_URL", get_settings().database_url.get_secret_value())
fixture = database.__wrapped__()
engine, sessions, url = next(fixture)
measurements = {}


def measure(label, function):
    started = time.perf_counter()
    result = function()
    measurements[label] = round((time.perf_counter() - started) * 1000, 3)
    return result


try:
    with tempfile.TemporaryDirectory() as directory:
        world, ingestion, ingest_worker = setup((engine, sessions, url), Path(directory))
        submitted = submit((world, ingestion, ingest_worker))
        ingest_worker.run_one(world.actor, world.definition.id)
        assert ingestion.get(world.actor, world.definition.id, submitted.id).status == "COMPLETED"
        service = SemanticService(sessions, world.objects.authorizer)
        worker = SemanticWorker(
            sessions,
            world.objects.authorizer,
            engine=OpenOntologiesAdapter(
                Path(os.environ.get("OPEN_ONTOLOGIES_BIN", ROOT / ".external/open-ontologies"))
            ),
        )
        p, ontology = world.actor, world.definition.id
        spec = ExportInput(
            schema_version=world.definition.version,
            selections=tuple(
                QueryRequest(object_type=t.id, limit=200) for t in world.definition.object_types
            ),
            links=tuple(t.id for t in world.definition.link_types),
        )
        tracemalloc.start()
        compiled = measure(
            "compile_ms",
            lambda: service.compile(p, ontology, CompileInput(schema_version=spec.schema_version)),
        )
        asserted = measure("export_63_ms", lambda: service.export(p, ontology, spec))
        assert asserted == measure("repeat_export_ms", lambda: service.export(p, ontology, spec))
        view = service.get(p, ontology, asserted)
        measurements["asserted_bytes_63"] = len(view.content.encode())
        for operation, secondary in (("validation", compiled[1]), ("reasoning", compiled[0])):
            run = service.submit(
                p,
                ontology,
                JobInput(
                    operation=operation, primary_artifact=asserted, secondary_artifact=secondary
                ),
            )
            measure(operation + "_job_ms", lambda: worker.run_one(p, ontology))
            assert service.job(p, ontology, run.id).status == "COMPLETED"
        for i in range(194):
            world.objects.create(
                p,
                ontology,
                CreateObject(
                    object_type_id="Factory",
                    object_id=f"SYN-{i}",
                    properties={
                        "factoryId": f"SYN-{i}",
                        "factoryName": "Synthetic",
                        "location": "Synthetic",
                    },
                ),
            )
        larger = measure("export_257_ms", lambda: service.export(p, ontology, spec))
        measurements["asserted_bytes_257"] = len(service.get(p, ontology, larger).content.encode())
        query = QueryService(sessions, world.objects.authorizer)
        action = ActionExecutionService(sessions, world.objects.authorizer)
        with ThreadPoolExecutor(max_workers=2) as pool:
            exported = pool.submit(
                measure, "concurrent_export_query_ms", lambda: service.export(p, ontology, spec)
            )
            queried = pool.submit(
                measure,
                "concurrent_query_ms",
                lambda: query.query(p, ontology, QueryRequest(object_type="Machine")),
            )
            exported.result()
            queried.result()
        with ThreadPoolExecutor(max_workers=2) as pool:
            exported = pool.submit(
                measure, "concurrent_export_action_ms", lambda: service.export(p, ontology, spec)
            )
            acted = pool.submit(
                measure,
                "concurrent_action_ms",
                lambda: action.execute(
                    p,
                    ontology,
                    "UpdateMachineStatus",
                    ExecuteRequest(
                        idempotency_key="semantic-benchmark",
                        parameters={
                            "machineId": "MCH-001",
                            "newStatus": "STOPPED",
                            "expectedRevision": 1,
                        },
                    ),
                ),
            )
            exported.result()
            acted.result()
        submitted = submit((world, ingestion, ingest_worker))
        with ThreadPoolExecutor(max_workers=2) as pool:
            exported = pool.submit(
                measure, "concurrent_export_ingestion_ms", lambda: service.export(p, ontology, spec)
            )
            ingested = pool.submit(
                measure, "concurrent_ingestion_ms", lambda: ingest_worker.run_one(p, ontology)
            )
            exported.result()
            ingested.result()
        assert ingestion.get(p, ontology, submitted.id).status == "COMPLETED"
        measurements["python_peak_bytes"] = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        measurements["process_peak_rss_platform_units"] = resource.getrusage(
            resource.RUSAGE_SELF
        ).ru_maxrss
finally:
    try:
        next(fixture)
    except StopIteration:
        pass
output = ROOT / "docs/architecture/evidence/phase-5/semantic-benchmarks.json"
output.write_text(json.dumps(measurements, indent=2) + "\n")
print(json.dumps(measurements, indent=2))
