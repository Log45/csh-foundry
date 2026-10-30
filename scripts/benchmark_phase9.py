"""Bounded local developer samples in a disposable migrated PostgreSQL schema; not load tests."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

from ontology_platform.branching.contracts import (
    BranchCreate,
    BranchEdit,
    ComparisonInput,
    MergeInput,
)
from ontology_platform.branching.service import BranchService
from ontology_platform.config import get_settings
from ontology_platform.main import create_app
from ontology_platform.sdk.generator import generate
from ontology_schema.models import OntologyDefinition

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api/tests"))
from test_phase1 import active, database, make_world  # noqa: E402

if not os.environ.get("TEST_DATABASE_URL"):
    os.environ["TEST_DATABASE_URL"] = get_settings().database_url.get_secret_value()
measurements: dict[str, object] = {
    "scope": "single local developer samples; local authorizer; no production throughput claim"
}


def measure(name, function):
    start = time.perf_counter()
    value = function()
    measurements[name + "_ms"] = round((time.perf_counter() - start) * 1000, 3)
    return value


fixture = database.__wrapped__()
try:
    w = make_world(next(fixture))
    data = w.definition.model_dump(mode="json")
    data["action_types"] = json.loads(
        (ROOT / "ontologies/examples/manufacturing-actions.json").read_text()
    )
    w.definition = OntologyDefinition.model_validate(data)
    active(w)
    service = BranchService(w.sessions, w.registry.authorizer)
    a = measure(
        "branch_creation",
        lambda: service.create(w.actor, w.definition.id, BranchCreate(name="source")),
    )
    b = service.create(w.actor, w.definition.id, BranchCreate(name="target"))
    changed = w.definition.model_copy(update={"name": "Changed"})
    measure(
        "revision_persistence",
        lambda: service.edit(
            w.actor,
            w.definition.id,
            a.id,
            BranchEdit(expected_revision=1, definition=changed, summary="Benchmark edit"),
        ),
    )
    measure(
        "comparison", lambda: service.comparison(w.actor, w.definition.id, a.id, ComparisonInput())
    )
    request = MergeInput(source_branch=a.id, source_revision=2, target_revision=1)
    preview = measure(
        "merge_preview", lambda: service.preview(w.actor, w.definition.id, b.id, request)
    )
    measure(
        "merge_execution",
        lambda: service.merge(
            w.actor,
            w.definition.id,
            b.id,
            request.model_copy(update={"preview_hash": preview.preview_hash}),
        ),
    )
    c, d = (
        service.create(w.actor, w.definition.id, BranchCreate(name=name)) for name in ("c", "d")
    )
    for row, name in ((c, "C"), (d, "D")):
        service.edit(
            w.actor,
            w.definition.id,
            row.id,
            BranchEdit(
                expected_revision=1,
                definition=w.definition.model_copy(update={"name": name}),
                summary="Conflict benchmark",
            ),
        )
    conflict = measure(
        "conflict_detection",
        lambda: service.preview(
            w.actor,
            w.definition.id,
            d.id,
            MergeInput(source_branch=c.id, source_revision=2, target_revision=2),
        ),
    )
    assert conflict.conflicts
    contract = create_app().openapi()
    data = w.definition.model_dump(mode="json")
    for i in range(10):
        data["object_types"].append(
            {
                "id": f"Synthetic{i}",
                "name": f"Synthetic {i}",
                "primary_key": "key",
                "properties": [
                    {"id": "key", "name": "Key", "data_type": "string", "required": True}
                ]
                + [
                    {"id": f"p{j}", "name": f"Property {j}", "data_type": "string"}
                    for j in range(10)
                ],
            }
        )
    large = OntologyDefinition.model_validate(data)
    measurements["large_schema_bytes"] = len(large.canonical_json().encode())
    from ontology_platform.branching.merge import three_way

    measure("large_schema_merge", lambda: three_way(large, large, large, []))
    tracemalloc.start()
    with tempfile.TemporaryDirectory(prefix="phase9-benchmark-") as folder:
        directory = Path(folder)
        for language in ("python", "typescript"):
            generated = measure(
                language + "_generation",
                lambda language=language: generate(w.definition, language, contract),
            )
            repeat = generate(w.definition, language, contract)
            assert repeat.archive() == generated.archive()
            measurements[language + "_source_bytes"] = sum(
                len(v.encode()) for v in generated.files.values()
            )
            measurements[language + "_archive_bytes"] = len(generated.archive())
            measurements[language + "_deterministic"] = True
            target = directory / language
            for name, content in generated.files.items():
                path = target / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            if language == "typescript":
                node = os.environ.get("FOUNDRY_TEST_NODE") or shutil.which("node")
                measure(
                    "typescript_package_build",
                    lambda node=node, target=target: subprocess.run(
                        [
                            node,
                            str(ROOT / "apps/studio/node_modules/typescript/bin/tsc"),
                            "-p",
                            str(target / "tsconfig.json"),
                        ],
                        check=True,
                        capture_output=True,
                    ),
                )
            else:
                measure(
                    "python_package_build",
                    lambda target=target: subprocess.run(
                        [
                            "uv",
                            "build",
                            str(target),
                            "--wheel",
                            "--out-dir",
                            str(directory / "wheels"),
                        ],
                        check=True,
                        capture_output=True,
                    ),
                )
        measure("large_schema_python_generation", lambda: generate(large, "python", contract))
    measurements["python_tracemalloc_peak_bytes"] = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
finally:
    fixture.close()
path = ROOT / "docs/architecture/evidence/phase-9/performance.json"
path.write_text(json.dumps(measurements, indent=2, sort_keys=True) + "\n")
print(path.read_text())
