"""Standalone Linux isolation smoke, suitable for an ephemeral constrained container."""

import json
import tempfile
from pathlib import Path

import polars as pl
from ontology_platform.execution.config import ExecutionSettings
from ontology_platform.execution.isolation import isolated


def main() -> None:
    limits = ExecutionSettings()
    with tempfile.TemporaryDirectory() as root:
        for format, content in [
            ("csv", b"id,value\n1,a\n2,b\n"),
            ("json", b'[{"id":1,"value":"a"}]'),
            ("ndjson", b'{"id":1,"value":"a"}\n'),
            ("parquet", b""),
        ]:
            directory = Path(root) / format
            directory.mkdir()
            source = directory / "source"
            if format == "parquet":
                pl.DataFrame({"id": [1], "value": ["a"]}).write_parquet(source)
            else:
                source.write_bytes(content)
            result = isolated(
                "validation", {"path": str(source), "format": format}, directory, limits
            )
            assert "error" not in result, result
            print("PASS Linux isolated", format, json.dumps(result["metrics"]), flush=True)
        directory = Path(root) / "pipeline"
        directory.mkdir()
        source = directory / "source.parquet"
        pl.DataFrame({"id": [1, 2, 3]}).write_parquet(source)
        request = {
            "specification": {
                "inputs": [{"name": "source"}],
                "steps": [{"op": "select", "columns": ["id"]}],
            },
            "inputs": [{"name": "source", "path": str(source), "format": "parquet"}],
        }
        result = isolated("pipeline", request, directory, limits)
        assert "error" not in result, result
        assert result["dataset"]["row_count"] == 3
        print("PASS Linux isolated Polars pipeline", json.dumps(result["metrics"]), flush=True)


if __name__ == "__main__":
    main()
