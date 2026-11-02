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


def verify(manifest: Path, root: Path, revision: str, images: dict[str, str]) -> None:
    data = json.loads(manifest.read_text())
    if data.get("source_revision") != revision or data.get("images") != images:
        raise ValueError("Evidence source revision or image identities do not match release")
    checks = data.get("checks", {})
    if REQUIRED - checks.keys():
        raise ValueError("Missing mandatory acceptance gates")
    for name in sorted(REQUIRED):
        check = checks[name]
        if check.get("result") != "PASS":
            raise ValueError("Acceptance gate is not PASS: " + name)
        path = (root / check["evidence"]).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError("Invalid evidence path: " + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != check.get("sha256"):
            raise ValueError("Evidence integrity mismatch: " + name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--image", action="append", required=True, help="ROLE=immutable image ID")
    args = parser.parse_args()
    try:
        images = dict(value.split("=", 1) for value in args.image)
        if set(images) != {"api", "studio", "semantic", "ingress"}:
            raise ValueError("API, Studio, semantic and ingress image identities required")
        verify(args.manifest, Path(__file__).resolve().parents[1], args.revision, images)
    except (ValueError, KeyError, OSError, TypeError) as error:
        raise SystemExit("BLOCKED: " + str(error)) from None
    print(
        "PASS mandatory local acceptance evidence integrity; owner/target approval remains separate"
    )


if __name__ == "__main__":
    main()
