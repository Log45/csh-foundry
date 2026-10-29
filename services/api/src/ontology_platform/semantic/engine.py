"""Batch-only semantic boundary. Never invoked from API request handlers."""

import hashlib
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
    files: dict[str, str] = {}


class SemanticEngine(Protocol):
    def validate_ontology(self, ontology_artifact: bytes) -> SemanticResult: ...
    def validate_shapes(self, shapes_artifact: bytes, data_artifact: bytes) -> SemanticResult: ...
    def reason(
        self,
        ontology_artifact: bytes,
        data_artifact: bytes,
        profile: Literal["owl-rl", "owl-rl-ext"] = "owl-rl-ext",
    ) -> SemanticResult: ...
    def derive(
        self,
        ontology_artifact: bytes,
        data_artifact: bytes,
        profile: Literal["owl-rl", "owl-rl-ext"],
    ) -> SemanticResult: ...
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
        self,
        operation: str,
        artifacts: dict[str, bytes],
        commands: list[tuple[str, list[str]]],
        outputs: tuple[str, ...] = (),
    ) -> SemanticResult:
        with tempfile.TemporaryDirectory(prefix="foundry-semantic-") as directory:
            root = Path(directory)
            (root / "certificate").mkdir()
            if any(len(data) > 4194304 for data in artifacts.values()):
                raise ApplicationError("semantic_resource_limit", "Input exceeds 4 MiB", 422)
            for name, content in artifacts.items():
                (root / name).write_bytes(content)
            payload = [
                {
                    "command": name,
                    "args": [
                        str(root / arg)
                        if arg in artifacts or arg in outputs or arg == "certificate"
                        else arg
                        for arg in args
                    ],
                }
                for name, args in commands
            ]
            try:
                with (root / "stdout").open("w+") as stdout:
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
                        stdout=stdout,
                        stderr=subprocess.DEVNULL,
                        text=True,
                        timeout=self.timeout_seconds,
                        check=False,
                    )
                    if stdout.tell() > 8388608:
                        raise ApplicationError(
                            "semantic_resource_limit", "Engine output exceeds 8 MiB", 422
                        )
                    stdout.seek(0)
                    raw_output = stdout.read()
            except subprocess.TimeoutExpired as exc:
                raise ApplicationError(
                    "semantic_timeout", "Semantic engine timed out", 504
                ) from exc
            except OSError as exc:
                raise ApplicationError(
                    "semantic_unavailable", "Semantic engine unavailable", 503
                ) from exc
            # Version identity is release-byte identity: this CLI has no --version flag.
            try:
                with self.executable.open("rb") as executable:
                    checksum = hashlib.file_digest(executable, "sha256").hexdigest()
            except OSError as exc:
                raise ApplicationError(
                    "semantic_unavailable", "Semantic engine unavailable", 503
                ) from exc
            if checksum not in {
                "493f6db51550112528d19f3ca88caf133b46c2a9054a195a98bc588b57ba07b6",
                "d2aacac75b2301eb3ce8f49000a8cc0bc7dd7edbf01fa36ac422ffdf4aaf11ee",
                "1d81ff3933868bfed001b63d8bdd6f9cb3c0807389d4e3064a51a41d7d60f480",
                "ead03c7148a66ea0fe01cbdaa289d47361c2a4d54619a60f805a72a2c57e81bb",
            }:
                raise ApplicationError(
                    "semantic_version_mismatch", "Engine checksum differs from pinned release", 503
                )
            try:
                records = [json.loads(line) for line in raw_output.splitlines() if line.strip()]
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
                files = {}
                total = 0
                for name in outputs:
                    target = root / name
                    total += target.stat().st_size
                    if total > 4194304:
                        raise ApplicationError(
                            "semantic_resource_limit", "Engine files exceed 4 MiB", 422
                        )
                    files[name] = target.read_text()
                return SemanticResult(operation=operation, records=records, files=files)
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
        return self._run(
            "diff",
            {"previous.ttl": previous_artifact, "proposed.ttl": proposed_artifact},
            [("diff", ["previous.ttl", "proposed.ttl"])],
        )

    def derive(
        self,
        ontology_artifact: bytes,
        data_artifact: bytes,
        profile: Literal["owl-rl", "owl-rl-ext"] = "owl-rl-ext",
    ) -> SemanticResult:
        if profile not in {"owl-rl", "owl-rl-ext"}:
            raise ApplicationError("unsupported_profile", "Unsupported reasoning profile", 422)
        return self._run(
            "derive",
            {"ontology.ttl": ontology_artifact, "data.ttl": data_artifact},
            [
                ("load", ["ontology.ttl"]),
                ("load", ["data.ttl"]),
                ("reason", ["--profile", profile, "--certificate", "certificate"]),
                ("save", ["closure.nt", "--format", "ntriples"]),
            ],
            outputs=(
                "closure.nt",
                "certificate/asserted.tsv",
                "certificate/derivations.tsv",
                "certificate/scope.tsv",
            ),
        )
