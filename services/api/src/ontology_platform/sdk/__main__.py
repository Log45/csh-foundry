"""Reproducible local published-export or authenticated remote SDK generation."""

import argparse
import json
import os
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

import httpx

from ontology_platform.contracts import VersionView
from ontology_platform.metadata.storage import digest
from ontology_platform.sdk.generator import generate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="Published VersionView JSON export")
    source.add_argument("--base-url", help="Platform API origin for authenticated remote workflow")
    parser.add_argument("--openapi", type=Path, help="Actual OpenAPI export; required with --input")
    parser.add_argument("--tenant", required=True, type=UUID)
    parser.add_argument("--ontology", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--language", choices=["python", "typescript"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--token-env", default="FOUNDRY_SDK_ACCESS_TOKEN")
    parser.add_argument(
        "--check", action="store_true", help="Compare generated files without writing"
    )
    args = parser.parse_args()
    if args.input:
        if not args.openapi:
            parser.error("--input requires --openapi")
        if args.input.stat().st_size > 131072 or args.openapi.stat().st_size > 5 * 1024 * 1024:
            parser.error("Generation inputs exceed size bounds")
        version = VersionView.model_validate_json(args.input.read_text())
        contract = json.loads(args.openapi.read_text())
    else:
        token = os.environ.get(args.token_env)
        if not token:
            parser.error("Token environment variable is missing")
        base = args.base_url.rstrip("/")
        if not base.startswith("https://") and not base.startswith(
            ("http://127.0.0.1:", "http://localhost:")
        ):
            parser.error("HTTPS required except loopback development")
        with httpx.Client(
            timeout=30,
            follow_redirects=False,
            trust_env=False,
            headers={"Authorization": "Bearer " + token, "X-Tenant-ID": str(args.tenant)},
        ) as client:
            url = (
                base
                + "/api/v1/ontologies/"
                + quote(args.ontology, safe="")
                + "/versions/"
                + quote(args.version, safe="")
            )
            with client.stream("GET", url) as response:
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 131072:
                        parser.error("Published schema response exceeds limit")
                version = VersionView.model_validate_json(bytes(raw))
            with client.stream("GET", base + "/api/v1/openapi.json") as response:
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 5 * 1024 * 1024:
                        parser.error("OpenAPI exceeds limit")
                contract = json.loads(raw)
    schema = version.definition
    if (
        version.status != "PUBLISHED"
        or digest(schema) != version.content_hash
        or (schema.tenant_id, schema.id, schema.version)
        != (args.tenant, args.ontology, args.version)
    ):
        parser.error("Input is not the selected immutable published schema/hash")
    generated = generate(schema, args.language, contract)
    if args.check:
        mismatches = [
            name
            for name, value in generated.files.items()
            if not (args.output / name).is_file() or (args.output / name).read_text() != value
        ]
        if mismatches:
            parser.error("Deterministic regeneration differs: " + ", ".join(mismatches))
    else:
        if args.output.exists() and any(args.output.iterdir()):
            parser.error("Output directory must be empty; use --check for regeneration")
        for name, value in generated.files.items():
            target = args.output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(value)
    print(json.dumps(generated.manifest, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
