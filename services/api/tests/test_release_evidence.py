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


@pytest.mark.parametrize(
    "mutation",
    [
        "none",
        "missing-service",
        "wrong-service",
        "failed-service",
        "missing-approval",
        "wrong-config",
        "missing-secret-identity",
        "wrong-profile",
        "missing-image",
        "high-finding",
        "failed-gate",
        "missing-rendered",
    ],
)
def test_external_profile_cannot_drop_infrastructure_or_image_gates(tmp_path, mutation):
    from hashlib import sha256

    def record(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value))
        return {"evidence": name, "sha256": sha256(path.read_bytes()).hexdigest()}

    images = {
        role: "sha256:" + str(i + 1) * 64 for i, role in enumerate(("api", "studio", "semantic"))
    }
    artifact = record("check.json", {"executed": True})
    data = {
        "source_revision": "candidate",
        "images": images,
        "deployment_profile": "okd",
        "checks": {name: artifact | {"result": "PASS"} for name in module.REQUIRED},
        "supply_chain": {},
        "external_services": {},
    }
    for role, identity in images.items():
        data["supply_chain"][role] = {
            "image_id": identity,
            "config_digest": identity,
            "scan": record(
                role + "-scan.json",
                {
                    "source": {"target": {"imageID": identity, "manifestDigest": identity}},
                    "descriptor": {"db": {"status": {"valid": True}}},
                    "matches": [{"vulnerability": {"severity": "High"}}]
                    if mutation == "high-finding"
                    else [],
                },
            ),
            "sbom": record(
                role + "-sbom.json",
                {
                    "bomFormat": "CycloneDX",
                    "metadata": {"component": {"version": identity}},
                    "components": ["runtime"],
                },
            ),
        }
    services = {"postgres": "db.example:5432/foundry", "keycloak": "https://id.example/realms/f"}
    for role, identity in services.items():
        assurance = {
            "identity": identity,
            "result": "PASS",
            "owner": "external-team",
            "version": "reviewed",
            "maintenance_responsibility": "external-team",
            "tls": "verified",
            "authentication": "reviewed",
            "compatibility_evidence": artifact,
            "security_approval_evidence": artifact,
            "operational_assurances": "reviewed",
        }
        if mutation == "failed-service":
            assurance["result"] = "NOT RUN"
        if mutation == "missing-approval":
            del assurance["security_approval_evidence"]
        data["external_services"][role] = record(role + ".json", assurance) | {"identity": identity}
    rendered = record("rendered.json", images)
    binding = {
        "rendered_manifest": rendered,
        "rendered_manifest_sha256": rendered["sha256"],
        "configuration_identities": [
            {"kind": kind, "name": kind, "uid": "object-uid", "resource_version": "1"}
            for kind in ("Secret", "ConfigMap")
        ],
    }
    if mutation == "missing-secret-identity":
        binding["configuration_identities"] = []
    if mutation == "missing-rendered":
        del binding["rendered_manifest"]
    configuration = record("config.json", binding)
    data["deployment_configuration"] = configuration
    if mutation == "missing-service":
        del data["external_services"]["postgres"]
    if mutation == "wrong-service":
        services["postgres"] = "different-database"
    if mutation == "wrong-profile":
        data["deployment_profile"] = "compose"
    if mutation == "missing-image":
        images.pop("api")
    if mutation == "failed-gate":
        data["checks"]["container_security"] = artifact | {"result": "FAIL"}
    manifest = tmp_path / "release.json"
    manifest.write_text(json.dumps(data))
    kwargs = {
        "profile": "okd",
        "external_services": services,
        "deployment_sha256": "a" * 64 if mutation == "wrong-config" else configuration["sha256"],
    }
    if mutation == "none":
        module.verify(manifest, tmp_path, "candidate", images, **kwargs)
    else:
        with pytest.raises((ValueError, KeyError)):
            module.verify(manifest, tmp_path, "candidate", images, **kwargs)
