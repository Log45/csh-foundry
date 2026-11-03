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
        json.dumps(
            {
                "source_revision": "candidate",
                "images": {
                    role: "sha256:" + str(i) * 64
                    for i, role in enumerate(sorted(module.IMAGE_ROLES))
                },
                "checks": {},
            }
        )
    )
    with pytest.raises(ValueError, match="identities"):
        module.verify(
            path,
            tmp_path,
            "other",
            {role: "sha256:" + str(i) * 64 for i, role in enumerate(sorted(module.IMAGE_ROLES))},
        )
    with pytest.raises(ValueError, match="Missing"):
        module.verify(
            path,
            tmp_path,
            "candidate",
            {role: "sha256:" + str(i) * 64 for i, role in enumerate(sorted(module.IMAGE_ROLES))},
        )


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
    supply = {}
    images = {role: "sha256:" + str(i) * 64 for i, role in enumerate(sorted(module.IMAGE_ROLES))}
    for role, identity in images.items():
        item = {"image_id": identity, "config_digest": identity}
        for kind, payload in {
            "scan": {
                "source": {"target": {"imageID": identity, "manifestDigest": identity}},
                "descriptor": {"db": {"status": {"valid": True}}},
                "matches": [],
            },
            "sbom": {
                "metadata": {"component": {"version": identity}},
                "bomFormat": "CycloneDX",
                "components": [{"name": "runtime"}],
            },
        }.items():
            evidence = tmp_path / (role + "." + kind + ".json")
            evidence.write_text(json.dumps(payload))
            item[kind] = {
                "evidence": evidence.name,
                "sha256": sha256(evidence.read_bytes()).hexdigest(),
            }
        supply[role] = item
    path = tmp_path / "manifest.json"
    data = {
        "source_revision": "candidate",
        "images": {
            role: "sha256:" + str(i) * 64 for i, role in enumerate(sorted(module.IMAGE_ROLES))
        },
        "checks": checks,
        "supply_chain": supply,
    }
    path.write_text(json.dumps(data))
    module.verify(
        path,
        tmp_path,
        "candidate",
        {role: "sha256:" + str(i) * 64 for i, role in enumerate(sorted(module.IMAGE_ROLES))},
    )
    checks["container_security"]["result"] = "BLOCKED"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="not PASS"):
        module.verify(
            path,
            tmp_path,
            "candidate",
            {role: "sha256:" + str(i) * 64 for i, role in enumerate(sorted(module.IMAGE_ROLES))},
        )
    checks["container_security"]["result"] = "PASS"
    checks["container_security"]["evidence"] = "../outside.txt"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="path"):
        module.verify(
            path,
            tmp_path,
            "candidate",
            {role: "sha256:" + str(i) * 64 for i, role in enumerate(sorted(module.IMAGE_ROLES))},
        )
    checks["container_security"]["evidence"] = artifact.name
    path.write_text(json.dumps(data))
    artifact.write_text("tampered")
    with pytest.raises(ValueError, match="integrity"):
        module.verify(
            path,
            tmp_path,
            "candidate",
            {role: "sha256:" + str(i) * 64 for i, role in enumerate(sorted(module.IMAGE_ROLES))},
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "high",
        "critical",
        "identity",
        "sbom",
        "db",
        "exception",
        "sbom-identity",
        "missing-sbom",
        "missing-scan",
        "missing-candidate",
        "incomplete-deployment",
        "signed-self-exception",
    ],
)
def test_release_raw_supply_chain_cannot_be_bypassed(tmp_path, mutation):
    from hashlib import sha256

    artifact = tmp_path / "evidence.txt"
    artifact.write_text("executed")
    images = {role: "sha256:" + str(i) * 64 for i, role in enumerate(sorted(module.IMAGE_ROLES))}
    record = {
        "evidence": artifact.name,
        "sha256": sha256(artifact.read_bytes()).hexdigest(),
        "result": "PASS",
    }
    data = {
        "source_revision": "candidate",
        "images": images,
        "checks": {name: record for name in module.REQUIRED},
        "supply_chain": {},
    }
    for role, identity in images.items():
        item = {"image_id": identity, "config_digest": identity}
        scan = {
            "source": {"target": {"imageID": identity, "manifestDigest": identity}},
            "descriptor": {"db": {"status": {"valid": True}}},
            "matches": [],
        }
        sbom = {
            "metadata": {"component": {"version": identity}},
            "bomFormat": "CycloneDX",
            "components": [{"name": "runtime"}],
        }
        if role == "postgres":
            if mutation in {"high", "critical", "exception"}:
                scan["matches"] = [
                    {
                        "vulnerability": {
                            "severity": "High" if mutation == "exception" else mutation.title()
                        }
                    }
                ]
            if mutation == "exception":
                item["risk_exception"] = {"approved": True, "authority": "self"}
            if mutation == "sbom-identity":
                sbom["metadata"]["component"]["version"] = images["api"]
            if mutation == "identity":
                scan["source"]["target"]["imageID"] = images["api"]
            if mutation == "sbom":
                sbom["components"] = []
            if mutation == "db":
                scan["descriptor"]["db"]["status"]["valid"] = False
        for kind, payload in {"scan": scan, "sbom": sbom}.items():
            path = tmp_path / (role + kind + ".json")
            path.write_text(json.dumps(payload))
            item[kind] = {"evidence": path.name, "sha256": sha256(path.read_bytes()).hexdigest()}
        data["supply_chain"][role] = item
    if mutation == "missing":
        del data["supply_chain"]["keycloak"]
    if mutation == "missing-sbom":
        del data["supply_chain"]["postgres"]["sbom"]
    if mutation == "missing-scan":
        del data["supply_chain"]["postgres"]["scan"]
    if mutation == "missing-candidate":
        del data["images"]["postgres"]
    if mutation == "incomplete-deployment":
        data["checks"]["combined_deployment"] = record | {"result": "NOT RUN"}
    if mutation == "signed-self-exception":
        data["dispositions"] = [{"signature": "self-signed", "authority": "developer"}]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(data))
    with pytest.raises((ValueError, KeyError)):
        module.verify(manifest, tmp_path, "candidate", images)
