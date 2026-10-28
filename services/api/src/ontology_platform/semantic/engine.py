"""Batch-only semantic boundary. Never invoked from API request handlers."""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, JsonValue

from ontology_platform.errors import ApplicationError

ENGINE_COMMIT = "ef6e781c71aaccaa35c2a1cd06169f0c862d5769"
ENGINE_VERSION = "2.1.0"


class SemanticResult(BaseModel):
    engine_version: str = ENGINE_VERSION
    engine_commit: str = ENGINE_COMMIT
    operation: str
    records: list[dict[str, JsonValue]]


class SemanticEngine(Protocol):
    def validate_ontology(self, ontology_artifact: bytes) -> SemanticResult: ...
    def validate_shapes(self, shapes_artifact: bytes, data_artifact: bytes) -> SemanticResult: ...
    def reason(self, ontology_artifact: bytes, data_artifact: bytes) -> SemanticResult: ...
    def analyze_change(
        self, previous_artifact: bytes, proposed_artifact: bytes
    ) -> SemanticResult: ...


class OpenOntologiesAdapter:
    """Pinned v2.1.0 CLI contract, JSON command arrays and JSON-lines results.

    The caller must install and checksum-verify the selected release binary.
    Each invocation has a disposable engine state directory; it is not an operational datastore.
    """

    def __init__(self, executable: Path, timeout_seconds: float = 30):
        if timeout_seconds <= 0:
            raise ValueError("Timeout must be positive")
        self.executable = executable.resolve()
        self.timeout_seconds = timeout_seconds

    def _run(
        self, operation: str, artifacts: dict[str, bytes], commands: list[tuple[str, list[str]]]
    ) -> SemanticResult:
        with tempfile.TemporaryDirectory(prefix="foundry-semantic-") as directory:
            root = Path(directory)
            for name, content in artifacts.items():
                (root / name).write_bytes(content)
            payload = [
                {
                    "command": name,
                    "args": [str(root / arg) if arg in artifacts else arg for arg in args],
                }
                for name, args in commands
            ]
            try:
                process = subprocess.run(
                    [
                        str(self.executable),
                        "--no-connect",
                        "--data-dir",
                        str(root / "state"),
                        "--json",
                        "batch",
                        "--bail",
                        "-",
                    ],
                    input=json.dumps(payload),
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise ApplicationError(
                    "semantic_timeout", "Semantic engine timed out", 504
                ) from exc
            except OSError as exc:
                raise ApplicationError(
                    "semantic_unavailable", "Semantic engine unavailable", 503
                ) from exc
            try:
                records = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
                if (
                    process.returncode != 0
                    or len(records) != len(commands)
                    or any(
                        not isinstance(r, dict)
                        or r.get("command") != commands[i][0]
                        or not isinstance(r.get("result"), dict)
                        or "error" in r["result"]
                        for i, r in enumerate(records)
                    )
                ):
                    raise ValueError("Engine operation failed or returned incomplete results")
                return SemanticResult(operation=operation, records=records)
            except (ValueError, TypeError, KeyError) as exc:
                # Do not expose stderr, paths or ontology content through API errors.
                raise ApplicationError(
                    "semantic_failed", "Semantic engine operation failed", 502
                ) from exc

    def validate_ontology(self, ontology_artifact: bytes) -> SemanticResult:
        return self._run(
            "parse",
            {"ontology.ttl": ontology_artifact},
            [("load", ["ontology.ttl"]), ("stats", [])],
        )

    def validate_shapes(self, shapes_artifact: bytes, data_artifact: bytes) -> SemanticResult:
        return self._run(
            "shacl",
            {"shapes.ttl": shapes_artifact, "data.ttl": data_artifact},
            [("load", ["data.ttl"]), ("shacl", ["shapes.ttl"])],
        )

    def reason(
        self,
        ontology_artifact: bytes,
        data_artifact: bytes,
        profile: Literal["owl-rl", "owl-rl-ext"] = "owl-rl-ext",
    ) -> SemanticResult:
        return self._run(
            "reason",
            {"ontology.ttl": ontology_artifact, "data.ttl": data_artifact},
            [
                ("load", ["ontology.ttl"]),
                ("load", ["data.ttl"]),
                ("reason", ["--profile", profile]),
                ("query", ["SELECT ?s ?type WHERE { ?s a ?type } ORDER BY ?s ?type"]),
            ],
        )

    def analyze_change(self, previous_artifact: bytes, proposed_artifact: bytes) -> SemanticResult:
        raise ApplicationError("semantic_not_supported", "Change analysis deferred to Phase 5", 501)
