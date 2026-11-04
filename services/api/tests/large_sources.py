"""Deterministic exact-byte sources generated at runtime; no committed large fixtures."""

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


def generate(path: Path, format: str, size: int) -> tuple[int, str]:
    payload = "0123456789abcdef" * 256
    if format == "parquet":
        # Stable schema metadata padding makes the complete valid Parquet exactly size bytes.
        rows = max(1, size // 4200 - 32)
        padding = 0
        for _ in range(6):
            schema = pa.schema(
                [("id", pa.int64()), ("payload", pa.string())],
                metadata={b"padding": b"x" * padding},
            )
            with pq.ParquetWriter(
                path, schema, compression="NONE", use_dictionary=False, store_schema=False
            ) as writer:
                writer.add_key_value_metadata(
                    {
                        f"padding-{i}": "x" * min(32768, padding - i * 32768)
                        for i in range((padding + 32767) // 32768)
                    }
                )
                for start in range(0, rows, 1024):
                    end = min(start + 1024, rows)
                    writer.write_table(
                        pa.table(
                            {"id": list(range(start, end)), "payload": [payload] * (end - start)},
                            schema=schema,
                        )
                    )
            difference = size - path.stat().st_size
            if difference == 0:
                break
            padding += difference
            if padding < 0:
                raise AssertionError("Parquet generator overhead exceeds reservation")
        assert path.stat().st_size == size
    else:
        template = (
            (payload + "\n").encode()
            if format == "csv"
            else (
                json.dumps({"payload": payload}, separators=(",", ":"))
                + ("\n" if format == "ndjson" else ",")
            ).encode()
        )
        prefix, suffix = (
            (b"payload\n", b"")
            if format == "csv"
            else (b"[", b"]")
            if format == "json"
            else (b"", b"")
        )
        rows = 0
        with path.open("wb") as file:
            file.write(prefix)
            budget = size - len(prefix) - len(suffix)
            # Leave room for one final nonempty, valid bounded record.
            while budget >= len(template) * 2:
                chunk_rows = min(1024, budget // len(template) - 1)
                file.write(template * chunk_rows)
                rows += chunk_rows
                budget -= len(template) * chunk_rows
            if format == "csv":
                last = b"x" * (budget - 1) + b"\n"
            elif format == "json":
                last = b'{"payload":"' + b"x" * (budget - len(b'{"payload":""}')) + b'"}'
            else:
                last = b'{"payload":"' + b"x" * (budget - len(b'{"payload":""}\n')) + b'"}\n'
            file.write(last)
            file.write(suffix)
            rows += 1
        assert path.stat().st_size == size
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(65536):
            digest.update(chunk)
    return rows, digest.hexdigest()
