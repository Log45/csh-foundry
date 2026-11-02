"""Promotion rejects incomplete gates, wrong release identities and changed evidence bytes."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "release_evidence", ROOT / "scripts/verify_release_evidence.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_release_requires_all_gates_and_exact_release_identities(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({"source_revision": "candidate", "images": {"api": "digest"}, "checks": {}})
    )
    with pytest.raises(ValueError, match="identities"):
        module.verify(path, tmp_path, "other", {"api": "digest"})
    with pytest.raises(ValueError, match="Missing"):
        module.verify(path, tmp_path, "candidate", {"api": "digest"})


def test_release_rejects_failed_gate_tampering_and_path_escape(tmp_path):
    from hashlib import sha256

    artifact = tmp_path / "evidence.txt"
    artifact.write_text("executed test evidence")
    checks = {
        name: {
            "result": "PASS",
            "evidence": artifact.name,
            "sha256": sha256(artifact.read_bytes()).hexdigest(),
        }
        for name in module.REQUIRED
    }
    path = tmp_path / "manifest.json"
    data = {"source_revision": "candidate", "images": {"api": "digest"}, "checks": checks}
    path.write_text(json.dumps(data))
    module.verify(path, tmp_path, "candidate", {"api": "digest"})
    checks["container_security"]["result"] = "BLOCKED"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="not PASS"):
        module.verify(path, tmp_path, "candidate", {"api": "digest"})
    checks["container_security"]["result"] = "PASS"
    checks["container_security"]["evidence"] = "../outside.txt"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="path"):
        module.verify(path, tmp_path, "candidate", {"api": "digest"})
    checks["container_security"]["evidence"] = artifact.name
    path.write_text(json.dumps(data))
    artifact.write_text("tampered")
    with pytest.raises(ValueError, match="integrity"):
        module.verify(path, tmp_path, "candidate", {"api": "digest"})
