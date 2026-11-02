"""Verify a downloaded SDK archive against a separately trusted digest; never extracts files."""

import argparse
from pathlib import Path

from ontology_platform.sdk.integrity import verify_archive

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("archive", type=Path)
parser.add_argument("--sha256", required=True)
parser.add_argument("--schema-hash")
parser.add_argument("--generator-version")
args = parser.parse_args()
if args.archive.stat().st_size > 8 * 1024 * 1024:
    parser.error("Archive exceeds bound")
result = verify_archive(
    args.archive.read_bytes(),
    args.sha256,
    schema_hash=args.schema_hash,
    generator_version=args.generator_version,
)
print("PASS SDK archive, inventory, file digests, canonical schema and generator constraints")
