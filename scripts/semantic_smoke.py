"""Persist actual engine results for the immutable manufacturing inputs."""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from ontology_platform.semantic.engine import OpenOntologiesAdapter

root = Path(__file__).resolve().parents[1]
fixtures = root / "fixtures"
engine = OpenOntologiesAdapter(
    Path(os.environ.get("OPEN_ONTOLOGIES_BIN", root / ".external/open-ontologies"))
)
ontology = (fixtures / "manufacturing.ttl").read_bytes()
data = (fixtures / "manufacturing-data.ttl").read_bytes()
shapes = (fixtures / "manufacturing-shapes.ttl").read_bytes()
results = {
    "generated_at": datetime.now(UTC).isoformat(),
    "inputs": {
        name: hashlib.sha256((fixtures / name).read_bytes()).hexdigest()
        for name in ["manufacturing.ttl", "manufacturing-data.ttl", "manufacturing-shapes.ttl"]
    },
    "parse": engine.validate_ontology(ontology).model_dump(),
    "shacl": engine.validate_shapes(shapes, data).model_dump(),
    "reasoning": {},
}
for profile in ("owl-rl", "owl-rl-ext"):
    result = engine.reason(ontology, data, profile=profile).model_dump()
    rows = result["records"][-1]["result"]["results"]
    result["critical_individuals"] = sorted(
        {r["s"].strip("<>") for r in rows if r["type"].strip("<>").endswith("#CriticalMachine")}
    )
    del result["records"][-1]
    results["reasoning"][profile] = result
output = root / "docs/architecture/evidence/semantic-smoke.json"
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(results, indent=2) + "\n")
print(f"Wrote {output}")
