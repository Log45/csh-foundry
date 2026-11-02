"""Independent verification of private SDK archives before installation or redistribution."""

import hashlib
import io
import json
import zipfile
from pathlib import PurePosixPath
from typing import Any

from ontology_schema.models import OntologyDefinition

from ontology_platform.branching.service import hash_payload
from ontology_platform.metadata.storage import digest


def verify_archive(
    archive: bytes,
    expected_sha256: str,
    *,
    schema_hash: str | None = None,
    generator_version: str | None = None,
) -> dict[str, Any]:
    """The expected digest must come from an authenticated, separately trusted channel."""
    if len(archive) > 8 * 1024 * 1024 or hashlib.sha256(archive).hexdigest() != expected_sha256:
        raise ValueError("Archive integrity mismatch")
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        files = zipped.infolist()
        if len(files) > 500 or sum(f.file_size for f in files) > 8 * 1024 * 1024:
            raise ValueError("Archive resource bound exceeded")
        names = [f.filename for f in files]
        if len(names) != len(set(names)) or any(
            PurePosixPath(name).is_absolute()
            or ".." in PurePosixPath(name).parts
            or "\\" in name
            or "\x00" in name
            for name in names
        ):
            raise ValueError("Unsafe archive member")
        manifest: dict[str, Any] = json.loads(zipped.read("manifest.json"))
        expected = manifest["files"]
        if set(expected) != set(names) - {"manifest.json"}:
            raise ValueError("Manifest file inventory mismatch")
        if any(
            hashlib.sha256(zipped.read(name)).hexdigest() != value
            for name, value in expected.items()
        ):
            raise ValueError("Manifest file hash mismatch")
        if hash_payload(expected) != manifest["artifact_content_hash"]:
            raise ValueError("Manifest content hash mismatch")
        schema = OntologyDefinition.model_validate_json(zipped.read("schema.json"))
        if digest(schema) != manifest["schema_hash"] or (
            schema_hash is not None and schema_hash != manifest["schema_hash"]
        ):
            raise ValueError("Schema hash mismatch")
        if generator_version is not None and manifest["generator_version"] != generator_version:
            raise ValueError("Untrusted generator version")
        if (str(schema.tenant_id), schema.id, schema.version) != (
            manifest["tenant_id"],
            manifest["ontology_id"],
            manifest["schema_version"],
        ):
            raise ValueError("Schema identity mismatch")
        return manifest
