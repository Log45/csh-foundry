"""Measure the spawned worker, independently of the controller's resident memory."""

import tempfile
from pathlib import Path

from ontology_platform.execution.config import ExecutionSettings
from ontology_platform.execution.isolation import isolated


def test_small_child_does_not_inherit_controller_high_watermark():
    controller_memory = bytearray(300 * 1024**2)
    controller_memory[::4096] = b"x" * (len(controller_memory) // 4096)
    request = {
        "specification": {
            "implementation": "identity.v1",
            "input_schema": {"text": {"type": "string"}},
            "output_schema": {"text": {"type": "string"}},
        },
        "inputs": {"text": "small"},
        "input_limit": 16384,
        "output_limit": 16384,
    }
    limits = ExecutionSettings(memory_bytes=128 * 1024**2)
    with tempfile.TemporaryDirectory() as directory:
        result = isolated("function", request, Path(directory), limits)
    assert len(controller_memory) > limits.memory_bytes
    assert result.get("values") == {"text": "small"}, result
    assert 0 < result["metrics"]["peak_memory_bytes"] <= limits.memory_bytes


def test_small_parquet_fits_bounded_address_space(tmp_path):
    import polars as pl

    source = tmp_path / "source.parquet"
    pl.DataFrame({"id": [1, 2], "value": ["x", None]}).write_parquet(source)
    limits = ExecutionSettings(address_bytes=1024**3, memory_bytes=256 * 1024**2)
    result = isolated("validation", {"path": str(source), "format": "parquet"}, tmp_path, limits)
    assert result.get("row_count") == 2, result
    assert result["preview"] == [[1, "x"], [2, None]]
    assert result["metrics"]["peak_memory_bytes"] <= limits.memory_bytes
