"""Full-content validation in a disposable process; cached, bounded source-order preview."""

import base64
import csv
import io
import json
import math
import multiprocessing
import resource
import subprocess
import sys
import tempfile
import time as clock
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any, BinaryIO

import polars as pl
import pyarrow.parquet as pq  # type: ignore[import-untyped]

WALL_SECONDS = 30
MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 256
MAX_DECODED = 32 * 1024 * 1024
PARSERS = BoundedSemaphore(2)
PARSER_VERSION = "phase13-v1/polars-" + pl.__version__


class InvalidDataset(ValueError):
    pass


def names(columns: list[str]) -> None:
    if len(columns) > MAX_COLUMNS or len(set(columns)) != len(columns):
        raise InvalidDataset("Too many or duplicate columns")
    if any(not c.strip() or len(c) > 200 or any(ord(x) < 32 for x in c) for c in columns):
        raise InvalidDataset("Column names must be nonempty, printable and at most 200 characters")


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in items]
    names(keys)
    return dict(items)


def safe(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        raise InvalidDataset("Nesting exceeds eight levels")
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidDataset("Nonfinite numbers are unsupported")
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        if len(value) > 65536:
            raise InvalidDataset("Binary cell exceeds 64 KiB")
        return {"base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, str):
        if len(value.encode("utf-8")) > 65536:
            raise InvalidDataset("Cell exceeds 64 KiB")
        return value
    if isinstance(value, list):
        return [safe(item, depth + 1) for item in value]
    if isinstance(value, dict):
        names(list(value))
        return {key: safe(item, depth + 1) for key, item in value.items()}
    raise InvalidDataset("Unsupported value type")


def shape(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items()}
    if isinstance(value, list):
        current = None
        for item in value:
            current = merge(current, shape(item))
        return ("list", current)
    return "number" if type(value) in (int, float) else type(value).__name__


def merge(left: Any, right: Any) -> Any:
    if left is None:
        return right
    if right is None:
        return left
    if isinstance(left, dict) and isinstance(right, dict) and left.keys() == right.keys():
        return {key: merge(left[key], right[key]) for key in left}
    if isinstance(left, tuple) and isinstance(right, tuple):
        return ("list", merge(left[1], right[1]))
    if left != right:
        raise InvalidDataset("Inconsistent JSON record keys or value types")
    return left


def parse(data: bytes, format: str) -> dict[str, Any]:
    if len(data) > MAX_BYTES:
        raise InvalidDataset("Dataset exceeds 8 MiB")
    physical = None
    if format == "parquet":
        parquet = pq.ParquetFile(
            io.BytesIO(data),
            thrift_string_size_limit=65536,
            thrift_container_size_limit=10000,
            arrow_extensions_enabled=False,
        )
        meta = parquet.metadata
        if meta.num_rows > MAX_ROWS or meta.num_columns > MAX_COLUMNS:
            raise InvalidDataset("Parquet exceeds row or column limits")
        expanded = sum(meta.row_group(i).total_byte_size for i in range(meta.num_row_groups))
        if expanded > MAX_DECODED:
            raise InvalidDataset("Parquet decoded size exceeds 32 MiB")
        physical = str(parquet.schema_arrow)
        frame = pl.DataFrame(parquet.read())
    elif format == "csv":
        text = data.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader, None)
        if not header:
            raise InvalidDataset("CSV requires a header")
        names(header)
        count = 0
        for row in reader:
            count += 1
            if len(row) != len(header) or count > MAX_ROWS:
                raise InvalidDataset("CSV row width or row limit violation")
        frame = pl.read_csv(
            io.BytesIO(text.encode("utf-8")),
            infer_schema_length=None,
            try_parse_dates=True,
            raise_if_empty=False,
        )
    elif format in ("json", "ndjson"):
        text = data.decode("utf-8")
        records = (
            json.loads(text, object_pairs_hook=pairs)
            if format == "json"
            else [
                json.loads(line, object_pairs_hook=pairs)
                for line in text.splitlines()
                if line.strip()
            ]
        )
        if not isinstance(records, list) or len(records) > MAX_ROWS:
            raise InvalidDataset("JSON requires an array of at most 100000 records")
        current = None
        for row in records:
            if not isinstance(row, dict) or not row:
                raise InvalidDataset("Every record must be a nonempty object")
            safe(row)
            current = merge(current, shape(row))
        frame = (
            pl.from_dicts(records, infer_schema_length=None, strict=True)
            if records
            else pl.DataFrame()
        )
    else:
        raise InvalidDataset("Unsupported dataset format")
    names(frame.columns)
    if frame.height > MAX_ROWS or frame.estimated_size() > MAX_DECODED:
        raise InvalidDataset("Decoded dataset exceeds limits")
    # Validate every value, including nesting and serialization, not just preview rows.
    preview = []
    preview_bytes = 0
    for i, record in enumerate(frame.iter_rows()):
        values = [safe(value) for value in record]
        if i < 100:
            preview_bytes += len(json.dumps(values).encode())
            if preview_bytes > 1024 * 1024:
                raise InvalidDataset("Preview exceeds 1 MiB")
            preview.append(values)
    columns = [
        {
            "name": name,
            "order": i,
            "logical_type": str(dtype),
            "nullable": frame[name].null_count() > 0,
        }
        for i, (name, dtype) in enumerate(frame.schema.items())
    ]
    return {
        "schema": columns,
        "row_count": frame.height,
        "column_count": frame.width,
        "preview": preview,
        "parser_version": PARSER_VERSION,
        "source_schema": physical,
        "validation": "full-content",
        "format": format,
    }


def worker(path: str, output: str, format: str) -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    try:
        from ontology_platform.datasets.streaming import validate_path
        from ontology_platform.execution.config import ExecutionSettings

        result = validate_path(Path(path), format, ExecutionSettings())
    except InvalidDataset as exc:
        result = {"error": "invalid_dataset", "message": str(exc)}
    except Exception:
        # Parser diagnostics can include private source values; publish a fixed category only.
        result = {
            "error": "invalid_dataset",
            "message": "Content violates format or validation limits",
        }
    Path(output).write_text(json.dumps(result, allow_nan=False))


def _validate(source: BinaryIO, format: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="foundry-dataset-") as directory:
        path, output = Path(directory) / "source", Path(directory) / "result"
        with path.open("wb") as file:
            remaining = MAX_BYTES + 1
            while remaining:
                chunk = source.read(min(65536, remaining))
                if not chunk:
                    break
                file.write(chunk)
                remaining -= len(chunk)
        if path.stat().st_size > MAX_BYTES:
            return {"error": "dataset_too_large", "message": "Dataset exceeds 8 MiB"}
        process = multiprocessing.get_context("spawn").Process(
            target=worker, args=(str(path), str(output), format)
        )
        process.start()
        deadline = clock.monotonic() + WALL_SECONDS
        try:
            while process.is_alive() and clock.monotonic() < deadline:
                process.join(0.1)
                # Darwin exposes no enforceable RLIMIT_AS. Monitor isolated child RSS as
                # a development safeguard in addition to source/decoded/deadline limits.
                if sys.platform == "darwin" and process.is_alive():
                    usage = subprocess.run(
                        ["/bin/ps", "-o", "rss=", "-p", str(process.pid)],
                        capture_output=True,
                        text=True,
                        timeout=1,
                        check=False,
                    )
                    if usage.returncode == 0 and int(usage.stdout.strip() or "0") > 512 * 1024:
                        break
        finally:
            if process.is_alive():
                process.kill()
            process.join()
        if process.exitcode != 0 or not output.exists():
            return {"error": "validation_failed", "message": "Parser exceeded execution limits"}
        return dict(json.loads(output.read_text()))


def validate(source: BinaryIO, format: str) -> dict[str, Any]:
    from ontology_platform.errors import ApplicationError

    if not PARSERS.acquire(blocking=False):
        raise ApplicationError(
            "validation_capacity", "Dataset validation is busy; retry finalization", 503
        )
    try:
        return _validate(source, format)
    finally:
        PARSERS.release()
