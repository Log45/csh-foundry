"""Fail promotion when mandatory local acceptance evidence is missing, failed or altered."""

import argparse
import hashlib
import json
import re
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


def verify(
    manifest: Path,
    root: Path,
    revision: str,
    images: dict[str, str],
    *,
    profile: str = "compose",
    external_services: dict[str, str] | None = None,
    deployment_sha256: str | None = None,
) -> None:
    data = json.loads(manifest.read_text())
    if data.get("source_revision") != revision or data.get("images") != images:
        raise ValueError("Evidence source revision or image identities do not match release")
    roles = IMAGE_ROLES if profile == "compose" else frozenset({"api", "studio", "semantic"})
    if profile not in {"compose", "okd", "self-hosted-kubernetes"}:
        raise ValueError("Unknown deployment profile")
    if data.get("deployment_profile", "compose") != profile:
        raise ValueError("Deployment profile mismatch")
    if set(images) != roles:
        raise ValueError("All selected image identities required for deployment profile")
    if profile != "compose":
        if not external_services or set(external_services) != {"postgres", "keycloak"}:
            raise ValueError("Explicit external PostgreSQL and Keycloak identities required")
        if not deployment_sha256 or not re.fullmatch(r"[a-f0-9]{64}", deployment_sha256):
            raise ValueError("Exact deployment configuration hash required")
        deployment = evidence_bytes(root, data["deployment_configuration"])
        if hashlib.sha256(deployment).hexdigest() != deployment_sha256:
            raise ValueError("Deployment configuration mismatch")
        binding = json.loads(deployment)
        if not binding.get("rendered_manifest_sha256") or not binding.get(
            "configuration_identities"
        ):
            raise ValueError("Rendered manifests and Secret/ConfigMap identities required")
        rendered = evidence_bytes(root, binding["rendered_manifest"])
        if hashlib.sha256(rendered).hexdigest() != binding["rendered_manifest_sha256"]:
            raise ValueError("Rendered deployment integrity mismatch")
        if not all(identity in rendered.decode() for identity in images.values()):
            raise ValueError("Deployment does not contain selected images")
        identities = binding["configuration_identities"]
        if (
            not isinstance(identities, list)
            or not all(
                all(item.get(k) for k in ("kind", "name", "uid", "resource_version"))
                for item in identities
            )
            or not {"Secret", "ConfigMap"} <= {item["kind"] for item in identities}
        ):
            raise ValueError("Secret/ConfigMap object identities incomplete")
        services = data.get("external_services", {})
        if set(services) != {"postgres", "keycloak"}:
            raise ValueError("Missing external infrastructure assessment")
        for role, identity in external_services.items():
            item = services[role]
            if item.get("identity") != identity:
                raise ValueError("External service identity mismatch")
            assurance = json.loads(evidence_bytes(root, item))
            if assurance.get("identity") != identity or assurance.get("result") != "PASS":
                raise ValueError("External compatibility/security assurance not PASS")
            if not all(
                assurance.get(k)
                for k in (
                    "owner",
                    "version",
                    "maintenance_responsibility",
                    "tls",
                    "authentication",
                    "compatibility_evidence",
                    "security_approval_evidence",
                    "operational_assurances",
                )
            ):
                raise ValueError("External service assurances incomplete")
            for name in ("compatibility_evidence", "security_approval_evidence"):
                evidence_bytes(root, assurance[name])
    # Hosted build provenance signs artifacts; it is not advisory-risk approval.
    # No independently administered disposition trust provider is configured.
    if data.get("dispositions"):
        raise ValueError("Independent disposition authorization unavailable; promotion blocked")
    checks = data.get("checks", {})
    if REQUIRED - checks.keys():
        raise ValueError("Missing mandatory acceptance gates")
    for name in sorted(REQUIRED):
        check = checks[name]
        if check.get("result") != "PASS":
            raise ValueError("Acceptance gate is not PASS: " + name)
        evidence_bytes(root, check)
    inventory = data.get("supply_chain", {})
    if set(inventory) != roles:
        raise ValueError("Missing selected-profile supply-chain evidence")
    for role in sorted(roles):
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
    parser.add_argument(
        "--profile", choices=("compose", "okd", "self-hosted-kubernetes"), default="compose"
    )
    parser.add_argument(
        "--service", action="append", default=[], help="ROLE=external service identity"
    )
    parser.add_argument("--deployment-sha256")
    args = parser.parse_args()
    try:
        images = dict(value.split("=", 1) for value in args.image)
        if len(images) != len(args.image):
            raise ValueError("Duplicate image role")
        services = dict(value.split("=", 1) for value in args.service)
        if len(services) != len(args.service):
            raise ValueError("Duplicate external service role")
        verify(
            args.manifest,
            Path(__file__).resolve().parents[1],
            args.revision,
            images,
            profile=args.profile,
            external_services=services,
            deployment_sha256=args.deployment_sha256,
        )
    except (ValueError, KeyError, OSError, TypeError) as error:
        raise SystemExit("BLOCKED: " + str(error)) from None
    print(
        "PASS mandatory local acceptance evidence integrity; owner/target approval remains separate"
    )


if __name__ == "__main__":
    main()
