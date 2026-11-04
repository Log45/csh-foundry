"""Full-file validation with bounded records/batches and a bounded preview.

CSV inference reconciles each bounded Polars batch over the entire source. JSON keys/types
are checked recursively before Polars conversion. No sampling establishes conformance.
"""

import csv
import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, TextIO

import polars as pl
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from ontology_platform.datasets.parser import InvalidDataset, merge, names, pairs, safe, shape
from ontology_platform.execution.config import ExecutionSettings

VERSION = "phase14-batched-v1/polars-" + pl.__version__


def json_records(file: TextIO, limit: int) -> Iterator[dict[str, Any]]:
    """Incremental array decoder; at most one bounded record plus a 64 KiB chunk."""
    decoder = json.JSONDecoder(object_pairs_hook=pairs)
    buffer, eof = "", False

    def more() -> None:
        nonlocal buffer, eof
        chunk = file.read(65536)
        eof = not chunk
        buffer += chunk
        if len(buffer.encode("utf-8")) > limit + 65536:
            raise InvalidDataset("JSON record exceeds configured limit")

    def whitespace() -> None:
        nonlocal buffer
        while True:
            buffer = buffer.lstrip(" \t\r\n")
            if buffer or eof:
                return
            more()

    whitespace()
    if not buffer.startswith("["):
        raise InvalidDataset("JSON requires an array")
    buffer = buffer[1:]
    whitespace()
    if buffer.startswith("]"):
        buffer = buffer[1:]
    else:
        while True:
            while True:
                try:
                    record, end = decoder.raw_decode(buffer)
                    break
                except json.JSONDecodeError:
                    if eof:
                        raise InvalidDataset("Malformed JSON array") from None
                    more()
            if len(buffer[:end].encode("utf-8")) > limit:
                raise InvalidDataset("JSON record exceeds configured limit")
            yield record
            buffer = buffer[end:]
            whitespace()
            if buffer.startswith("]"):
                buffer = buffer[1:]
                break
            if not buffer.startswith(","):
                raise InvalidDataset("Malformed JSON array separator")
            buffer = buffer[1:]
            whitespace()
    whitespace()
    if buffer:
        raise InvalidDataset("Trailing JSON content")


def ndjson_records(file: TextIO, limit: int) -> Iterator[dict[str, Any]]:
    while line := file.readline(limit + 1):
        if len(line.encode("utf-8")) > limit:
            raise InvalidDataset("NDJSON record exceeds configured limit")
        if line.strip():
            yield json.loads(line, object_pairs_hook=pairs)


def ordered(value: Any, structure: Any) -> Any:
    if isinstance(value, dict) and isinstance(structure, dict):
        return {key: ordered(value[key], item) for key, item in structure.items()}
    if isinstance(value, list) and isinstance(structure, tuple):
        return [ordered(item, structure[1]) for item in value]
    return value


def text_batches(
    path: Path, format: str, limits: ExecutionSettings, string_columns: tuple[str, ...] = ()
) -> Iterator[pl.DataFrame]:
    with path.open(encoding="utf-8-sig" if format == "csv" else "utf-8", newline="") as file:
        if format == "csv":
            csv.field_size_limit(65536)

            def lines() -> Iterator[str]:
                while line := file.readline(limits.record_bytes + 1):
                    if len(line.encode("utf-8")) > limits.record_bytes:
                        raise InvalidDataset("CSV physical line exceeds configured record limit")
                    yield line

            reader = csv.reader(lines(), strict=True)
            header = next(reader, None)
            if not header:
                raise InvalidDataset("CSV requires a header")
            names(header)
            if len(header) > limits.columns:
                raise InvalidDataset("Schema exceeds configured width")
            rows: list[Any] = []
            size = 0
            emitted = False
            for row in reader:
                if len(row) != len(header):
                    raise InvalidDataset("CSV row width violation")
                row_size = sum(len(value.encode("utf-8")) for value in row)
                if row_size > limits.record_bytes:
                    raise InvalidDataset("CSV record exceeds configured limit")
                rows.append(row)
                size += row_size + len(row)
                if size >= limits.batch_bytes or len(rows) >= 8192:
                    yield csv_frame(header, rows, string_columns)
                    emitted = True
                    rows, size = [], 0
            if rows or not emitted:
                # A header-only frame also preserves schema for an empty source.
                yield csv_frame(header, rows, string_columns)
        else:
            records = (
                json_records(file, limits.record_bytes)
                if format == "json"
                else ndjson_records(file, limits.record_bytes)
            )
            current = None
            rows, size = [], 0
            for record in records:
                if not isinstance(record, dict) or not record:
                    raise InvalidDataset("Every record must be a nonempty object")
                safe(record)
                current = merge(current, shape(record))
                rows.append(ordered(record, current))
                size += len(json.dumps(record).encode("utf-8"))
                if size >= limits.batch_bytes or len(rows) >= 8192:
                    yield pl.from_dicts(rows, infer_schema_length=None, strict=True)
                    rows, size = [], 0
            if rows:
                yield pl.from_dicts(rows, infer_schema_length=None, strict=True)


def csv_frame(
    header: list[str], rows: list[Any], string_columns: tuple[str, ...] = ()
) -> pl.DataFrame:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    frame = pl.read_csv(
        io.BytesIO(buffer.getvalue().encode()),
        infer_schema_length=None,
        schema_overrides={column: pl.String for column in string_columns},
        try_parse_dates=True,
        raise_if_empty=False,
    )
    # An all-null batch must not widen a numeric column observed in another batch to String.
    if frame.height:
        frame = frame.with_columns(
            [
                pl.col(c).cast(pl.Null)
                for c in frame.columns
                if frame[c].null_count() == frame.height
            ]
        )
    return frame


def parquet_file(path: Path) -> Any:
    return pq.ParquetFile(
        path,
        thrift_string_size_limit=65536,
        thrift_container_size_limit=10000,
        arrow_extensions_enabled=False,
        page_checksum_verification=True,
    )


def arrow_type(dtype: Any, depth: int = 1) -> None:
    if depth > 8:
        raise InvalidDataset("Nesting exceeds eight levels")
    if pa.types.is_struct(dtype):
        names([field.name for field in dtype])
        for field in dtype:
            arrow_type(field.type, depth + 1)
    elif (
        pa.types.is_list(dtype)
        or pa.types.is_large_list(dtype)
        or pa.types.is_fixed_size_list(dtype)
    ):
        arrow_type(dtype.value_type, depth + 1)


def batches(
    path: Path, format: str, limits: ExecutionSettings, *, string_columns: tuple[str, ...] = ()
) -> Iterator[pl.DataFrame]:
    if format in {"csv", "json", "ndjson"}:
        yield from text_batches(path, format, limits, string_columns)
    elif format == "parquet":
        parquet = parquet_file(path)
        for field in parquet.schema_arrow:
            arrow_type(field.type)
        metadata = parquet.metadata
        if metadata.num_rows > limits.rows or metadata.num_columns > limits.columns:
            raise InvalidDataset("Parquet exceeds row or column limits")
        expanded = 0
        for i in range(metadata.num_row_groups):
            group = metadata.row_group(i).total_byte_size
            expanded += group
            if group > limits.row_group_bytes or expanded > limits.decoded_bytes:
                raise InvalidDataset("Parquet decoded metadata exceeds limits")
        for batch in parquet.iter_batches(batch_size=1024, use_threads=False):
            yield pl.from_arrow(batch)  # type: ignore[misc]
        if metadata.num_rows == 0:
            yield pl.from_arrow(parquet.schema_arrow.empty_table())  # type: ignore[misc]
    else:
        raise InvalidDataset("Unsupported dataset format")


def validate_path(path: Path, format: str, limits: ExecutionSettings) -> dict[str, Any]:
    if path.stat().st_size > limits.source_bytes:
        raise InvalidDataset("Dataset exceeds configured source limit")
    count, decoded = 0, 0
    schema: pl.DataFrame | None = None
    nullable: dict[str, bool] = {}
    preview: list[dict[str, Any]] = []
    for frame in batches(path, format, limits):
        names(frame.columns)
        if frame.width > limits.columns:
            raise InvalidDataset("Schema exceeds configured width")
        count += frame.height
        decoded += int(frame.estimated_size())
        if count > limits.rows or decoded > limits.decoded_bytes:
            raise InvalidDataset("Dataset exceeds configured row or decoded limit")
        if frame.estimated_size() > limits.batch_bytes * 4:
            raise InvalidDataset("Decoded batch exceeds configured limit")
        schema = (
            frame.clear()
            if schema is None
            else pl.concat([schema, frame.clear()], how="vertical_relaxed")
        )
        for column in frame.columns:
            nullable[column] = nullable.get(column, False) or frame[column].null_count() > 0
        for i, row in enumerate(frame.iter_rows(named=True)):
            safe(row)
            if count - frame.height + i < 100:
                preview.append(row)
    if format == "parquet" and count != parquet_file(path).metadata.num_rows:
        raise InvalidDataset("Parquet footer row count does not match decoded records")
    schema = schema if schema is not None else pl.DataFrame()
    if format == "csv":
        schema = schema.cast({c: pl.String for c, t in schema.schema.items() if t == pl.Null})
    # Cast the bounded preview to the reconciled schema, preserving source column order.
    values = (
        pl.from_dicts(preview, infer_schema_length=None).cast(schema.schema).rows()
        if preview
        else []
    )
    serialized = [[safe(value) for value in row] for row in values]
    if len(json.dumps(serialized).encode()) > 1024**2:
        raise InvalidDataset("Preview exceeds 1 MiB")
    physical = (
        str(parquet_file(path).schema_arrow.remove_metadata()) if format == "parquet" else None
    )
    if len(str(physical).encode()) > 1024**2 or len(str(schema.schema).encode()) > 1024**2:
        raise InvalidDataset("Schema exceeds 1 MiB")
    return {
        "schema": [
            {"name": name, "order": i, "logical_type": str(dtype), "nullable": nullable[name]}
            for i, (name, dtype) in enumerate(schema.schema.items())
        ],
        "row_count": count,
        "column_count": schema.width,
        "preview": serialized,
        "parser_version": VERSION,
        "source_schema": physical,
        "validation": "full-content",
        "format": format,
        "decoded_bytes": decoded,
    }
