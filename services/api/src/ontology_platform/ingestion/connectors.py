"""Bounded registered source snapshots, with redacted parse diagnostics."""

import csv
import hashlib
import io
import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from uuid import UUID

import polars as pl
from pydantic import JsonValue
from sqlalchemy import MetaData, Table, create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError

from ontology_platform.errors import ApplicationError
from ontology_platform.ingestion.catalog import Binding

MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_ROWS = 10000
MAX_ROW_BYTES = 16384


@dataclass
class Record:
    number: int
    values: dict[str, JsonValue]
    error: str | None = None


@dataclass
class Extraction:
    rows: list[Record]
    fingerprint: str
    eof: bool


def encode(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def normalized(value: Any) -> JsonValue:
    if isinstance(value, (date, datetime, Decimal, UUID)):
        return value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    if value is None or type(value) in (str, int, float, bool):
        return cast(JsonValue, value)
    raise ValueError("Unsupported source value")


def record(number: int, values: dict[str, Any], binding: Binding) -> Record:
    try:
        if set(values) != {c.name for c in binding.columns}:
            raise ValueError("Source columns differ")
        result = {k: normalized(v) for k, v in values.items()}
        if len(encode(result)) > MAX_ROW_BYTES:
            return Record(number, {}, "source_row_too_wide")
        for column in binding.columns:
            value = result[column.name]
            if value is None:
                if not column.nullable:
                    raise ValueError("Null source column")
            elif binding.kind != "csv":
                expected = {"integer": int, "float": float, "boolean": bool}.get(
                    column.data_type, str
                )
                if type(value) is not expected:
                    raise ValueError("Source column type differs")
        return Record(number, result)
    except (ValueError, TypeError):
        return Record(number, {}, "source_type_error")


def predicate_value(binding: Binding, name: str, value: str | int | float | bool | None) -> object:
    kind = next(c.data_type for c in binding.columns if c.name == name)
    if value is None:
        return None
    try:
        if kind == "date":
            assert isinstance(value, str)
            parsed = date.fromisoformat(value)
            if parsed.isoformat() != value:
                raise ValueError("Noncanonical date")
            return parsed
        if kind == "timestamp":
            assert isinstance(value, str)
            instant = datetime.fromisoformat(value)
            if instant.utcoffset() is None:
                raise ValueError("Timezone required")
            return instant
        if kind == "decimal":
            assert isinstance(value, str)
            number = Decimal(value)
            if not number.is_finite():
                raise ValueError("Finite decimal required")
            return number
        if kind == "uuid":
            assert isinstance(value, str)
            identifier = UUID(value)
            if str(identifier) != value:
                raise ValueError("Noncanonical UUID")
            return identifier
        return value
    except (ValueError, InvalidOperation) as exc:
        raise ApplicationError(
            "invalid_registration", "Invalid typed source predicate", 422
        ) from exc


def postgres(binding: Binding, offset: int, size: int) -> Extraction:
    started = time.monotonic()
    if (
        binding.url is None
        or binding.table is None
        or not binding.url.get_secret_value().startswith("postgresql+psycopg://")
    ):
        raise ApplicationError("source_unavailable", "PostgreSQL registration is incomplete", 422)
    engine = create_engine(
        binding.url.get_secret_value(),
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=5000"},
    )
    selected: list[Record] = []
    digest = hashlib.sha256()
    total = 0
    count = 0
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                unsafe = connection.scalar(
                    text("""SELECT rolsuper OR rolcreaterole OR rolcreatedb
                    FROM pg_roles WHERE rolname=current_user""")
                )
                table = Table(
                    binding.table, MetaData(), schema=binding.table_schema, autoload_with=connection
                )
                name = connection.dialect.identifier_preparer.format_table(table)
                writable = connection.scalar(
                    text("""SELECT has_table_privilege(current_user,:table,
                    'INSERT,UPDATE,DELETE,TRUNCATE,TRIGGER') OR
                    has_any_column_privilege(current_user,:table,'INSERT,UPDATE')"""),
                    {"table": name},
                )
                if unsafe or writable:
                    raise ApplicationError(
                        "source_credentials_not_readonly",
                        "Source role must have read-only privileges",
                        403,
                    )
                names = [c.name for c in binding.columns]
                if not set(names) <= set(table.c.keys()):
                    raise ApplicationError(
                        "source_schema_error",
                        "Registered columns are missing",
                        422,
                    )
                if not set(binding.equals) <= set(names):
                    raise ApplicationError(
                        "source_schema_error", "Predicate column is not allowlisted", 422
                    )
                statement = (
                    select(*(table.c[n] for n in names))
                    .where(
                        *(
                            table.c[name] == predicate_value(binding, name, value)
                            for name, value in binding.equals.items()
                        )
                    )
                    .order_by(
                        *(list(table.primary_key.columns) or [table.c[name] for name in names])
                    )
                    .limit(MAX_ROWS + 1)
                )
                result = connection.execution_options(stream_results=True, yield_per=size).execute(
                    statement
                )
                for index, row in enumerate(result.mappings()):
                    count = index + 1
                    if time.monotonic() - started > 5:
                        raise ApplicationError(
                            "source_read_timeout", "Source snapshot exceeded five seconds", 503
                        )
                    if count > MAX_ROWS:
                        raise ApplicationError("source_too_large", "Source exceeds row limit", 422)
                    values = {k: normalized(v) for k, v in row.items()}
                    encoded = encode(values)
                    total += len(encoded)
                    if total > MAX_FILE_BYTES:
                        raise ApplicationError(
                            "source_too_large", "Source exceeds snapshot byte limit", 422
                        )
                    digest.update(encoded + b"\n")
                    if offset <= index < offset + size:
                        selected.append(record(index + 1, values, binding))
        if time.monotonic() - started > 5:
            raise ApplicationError(
                "source_read_timeout", "Source snapshot exceeded five seconds", 503
            )
        return Extraction(selected, digest.hexdigest(), offset + size >= count)
    except SQLAlchemyError as exc:
        raise ApplicationError(
            "source_read_error", "Registered PostgreSQL read failed", 503
        ) from exc
    finally:
        engine.dispose()


def extract(binding: Binding, offset: int, size: int) -> Extraction:
    if binding.kind == "postgres":
        return postgres(binding, offset, size)
    started = time.monotonic()
    path = binding.path()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        body = stream.read(MAX_FILE_BYTES + 1)
    if len(body) > MAX_FILE_BYTES:
        raise ApplicationError("source_too_large", "Source file exceeds 16 MiB", 422)
    fingerprint = hashlib.sha256(body).hexdigest()
    rows: list[Record] = []
    names = [c.name for c in binding.columns]
    count = 0
    csv_eof: bool | None = None
    try:
        if binding.kind == "parquet":
            schema = pl.read_parquet_schema(io.BytesIO(body))
            if set(schema) != set(names):
                raise ValueError("Parquet columns differ")
            scan = pl.scan_parquet(io.BytesIO(body), glob=False, credential_provider=None)
            count = scan.select(pl.len()).collect(engine="streaming").item()
            if count > MAX_ROWS:
                raise ApplicationError("source_too_large", "Source exceeds row limit", 422)
            aliases = {name: f"_column_{i}" for i, name in enumerate(names)}
            frame = (
                scan.rename(aliases)
                .select(list(aliases.values()))
                .slice(offset, size)
                .collect(engine="streaming")
                .rename({v: k for k, v in aliases.items()})
            )
            rows = [
                record(offset + i + 1, r, binding)
                for i, r in enumerate(frame.iter_rows(named=True))
            ]
        elif binding.kind == "csv":
            reader = csv.reader(
                io.StringIO(body.decode("utf-8-sig")), delimiter=binding.delimiter, strict=True
            )
            header = next(reader, [])
            if len(set(header)) != len(header) or set(header) != set(names):
                raise ApplicationError(
                    "source_header_error", "CSV headers differ from registered columns", 422
                )
            for index, values in enumerate(reader):
                count = index + 1
                if count > MAX_ROWS:
                    raise ApplicationError("source_too_large", "Source exceeds row limit", 422)
                if offset <= index < offset + size:
                    if len(values) != len(header):
                        rows.append(Record(count, {}, "source_parse_error"))
                    else:
                        rows.append(record(count, dict(zip(header, values, strict=True)), binding))
                if count >= offset + size:
                    # Continue counting no further than one extra row to identify EOF.
                    extra = next(reader, None)
                    csv_eof = extra is None
                    break
        else:
            # JSON is newline-delimited JSON objects, never an unbounded top-level array.
            for index, line in enumerate(io.BytesIO(body)):
                count = index + 1
                if count > MAX_ROWS:
                    raise ApplicationError("source_too_large", "Source exceeds row limit", 422)
                if offset <= index < offset + size:
                    if len(line) > MAX_ROW_BYTES:
                        rows.append(Record(count, {}, "source_row_too_wide"))
                    else:
                        try:
                            value = json.loads(line)
                            if not isinstance(value, dict):
                                raise ValueError("NDJSON objects required")
                            rows.append(record(count, value, binding))
                        except (ValueError, TypeError):
                            rows.append(Record(count, {}, "source_parse_error"))
        if time.monotonic() - started > 5:
            raise ApplicationError(
                "transformation_timeout", "Source extraction exceeded five seconds", 503
            )
        return Extraction(
            rows, fingerprint, csv_eof if csv_eof is not None else offset + size >= count
        )
    except (ValueError, UnicodeError, csv.Error, pl.exceptions.PolarsError) as exc:
        raise ApplicationError("source_parse_error", "Source parsing failed", 422) from exc
