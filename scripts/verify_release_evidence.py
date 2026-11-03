"""Fail promotion when mandatory local acceptance evidence is missing, failed or altered."""

import argparse
import hashlib
import json
from pathlib import Path

REQUIRED = frozenset(
    {
        "regression",
        "container_security",
        "combined_deployment",
        "manufacturing",
        "sessions",
        "worker_recovery",
        "semantic_isolation",
        "database_recovery",
        "monitoring_delivery",
        "quotas",
        "load",
        "failure_injection",
        "secret_rotation",
        "role_revocation",
        "sdk_integrity",
        "rollback",
        "sbom",
    }
)


IMAGE_ROLES = frozenset({"api", "studio", "semantic", "ingress", "postgres", "keycloak"})


def evidence_bytes(root: Path, record: dict) -> bytes:
    path = (root / record["evidence"]).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Invalid evidence path")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != record.get("sha256"):
        raise ValueError("Evidence integrity mismatch")
    return raw


def verify(manifest: Path, root: Path, revision: str, images: dict[str, str]) -> None:
    data = json.loads(manifest.read_text())
    if data.get("source_revision") != revision or data.get("images") != images:
        raise ValueError("Evidence source revision or image identities do not match release")
    if set(images) != IMAGE_ROLES:
        raise ValueError("All six selected image identities required")
    checks = data.get("checks", {})
    if REQUIRED - checks.keys():
        raise ValueError("Missing mandatory acceptance gates")
    for name in sorted(REQUIRED):
        check = checks[name]
        if check.get("result") != "PASS":
            raise ValueError("Acceptance gate is not PASS: " + name)
        evidence_bytes(root, check)
    inventory = data.get("supply_chain", {})
    if set(inventory) != IMAGE_ROLES:
        raise ValueError("Missing six-image supply-chain evidence")
    for role in sorted(IMAGE_ROLES):
        item = inventory[role]
        if item.get("image_id") != images[role]:
            raise ValueError("Supply-chain image identity mismatch: " + role)
        scan = json.loads(evidence_bytes(root, item["scan"]))
        sbom = json.loads(evidence_bytes(root, item["sbom"]))
        if scan.get("source", {}).get("target", {}).get("imageID") != item["config_digest"]:
            raise ValueError("Scanner image identity mismatch: " + role)
        if not scan.get("descriptor", {}).get("db", {}).get("status", {}).get("valid"):
            raise ValueError("Scanner database is not valid: " + role)
        if not isinstance(scan.get("matches"), list):
            raise ValueError("Missing scanner matches: " + role)
        if any(
            m["vulnerability"]["severity"].lower() in {"high", "critical"} for m in scan["matches"]
        ):
            raise ValueError("High/critical findings block promotion: " + role)
        if sbom.get("metadata", {}).get("component", {}).get("version") != scan.get(
            "source", {}
        ).get("target", {}).get("manifestDigest"):
            raise ValueError("SBOM/scanner platform identity mismatch: " + role)
        if sbom.get("bomFormat") != "CycloneDX" or not sbom.get("components"):
            raise ValueError("Missing CycloneDX package inventory: " + role)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--image", action="append", required=True, help="ROLE=immutable image ID")
    args = parser.parse_args()
    try:
        images = dict(value.split("=", 1) for value in args.image)
        if set(images) != IMAGE_ROLES:
            raise ValueError("All six selected image identities required")
        verify(args.manifest, Path(__file__).resolve().parents[1], args.revision, images)
    except (ValueError, KeyError, OSError, TypeError) as error:
        raise SystemExit("BLOCKED: " + str(error)) from None
    print(
        "PASS mandatory local acceptance evidence integrity; owner/target approval remains separate"
    )


if __name__ == "__main__":
    main()
