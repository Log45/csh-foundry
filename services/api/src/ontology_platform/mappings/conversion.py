"""Strict, deterministic scalar conversions shared by preview and full processing."""

import hashlib
import json
import math
import re
import unicodedata
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from ontology_platform.mappings.contracts import Identity, Value


def convert(value: Any, kind: str) -> Any:
    if value is None:
        raise ValueError("Null scalar")
    if kind == "string":
        if not isinstance(value, str):
            raise ValueError("String conversion requires string input")
        return unicodedata.normalize("NFC", value)
    if kind == "integer":
        if type(value) is int:
            number = value
        elif isinstance(value, str) and re.fullmatch(r"[+-]?[0-9]+", value):
            number = int(value)
        else:
            raise ValueError("Invalid integer")
        if not -(2**63) <= number < 2**63:
            raise ValueError("Integer overflow")
        return number
    if kind == "decimal":
        if type(value) not in {int, str, Decimal}:
            raise ValueError("Decimal conversion would lose precision")
        try:
            decimal_value = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("Invalid decimal") from exc
        if (
            not decimal_value.is_finite()
            or len(decimal_value.as_tuple().digits) > 38
            or abs(decimal_value.adjusted()) > 38
            or abs(int(decimal_value.as_tuple().exponent)) > 38
        ):
            raise ValueError("Nonfinite decimal")
        # format without normalize(): normalize uses the ambient decimal precision context.
        result = format(decimal_value, "f")
        return (
            (result.rstrip("0").rstrip(".") if "." in result else result) if decimal_value else "0"
        )
    if kind == "float":
        if type(value) not in {int, float, str}:
            raise ValueError("Invalid float")
        float_value = float(value)
        if not math.isfinite(float_value) or (type(value) is int and int(float_value) != value):
            raise ValueError("Float overflow or precision loss")
        return float_value
    if kind == "boolean":
        if type(value) is bool:
            return value
        if value in ("true", "false"):
            return value == "true"
        raise ValueError("Invalid boolean")
    if kind == "date":
        if type(value) is date:
            return value.isoformat()
        if isinstance(value, str) and date.fromisoformat(value).isoformat() == value:
            return value
        raise ValueError("Invalid date")
    if kind == "timestamp":
        if not isinstance(value, (str, datetime)):
            raise ValueError("Invalid timestamp")
        if isinstance(value, str) and re.search(r"\.\d{7,}", value):
            raise ValueError("Submicrosecond truncation is unsupported")
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if parsed.utcoffset() is None:
            raise ValueError("Timestamp requires timezone")
        return parsed.astimezone(UTC).isoformat()
    if kind == "uuid":
        if not isinstance(value, str):
            raise ValueError("Invalid UUID")
        return str(UUID(value))
    raise ValueError("Unsupported conversion")


def evaluate(spec: Value, row: dict[str, Any]) -> Any:
    value = row[spec.column] if spec.column is not None else spec.constant
    if value is None:
        if spec.nulls == "allow":
            return None
        if spec.nulls == "default":
            value = spec.default
    return convert(value, spec.conversion)


def identity(spec: Identity, row: dict[str, Any]) -> str:
    values = [(v.conversion, evaluate(v, row)) for v in spec.components]
    if len(values) == 1:
        kind, value = values[0]
        result = str(value).lower() if kind == "boolean" else str(value)
    else:
        payload = json.dumps(
            [1, values], ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
        result = "composite-v1-" + hashlib.sha256(payload.encode()).hexdigest()
    if not result or len(result) > 200 or any(ord(c) < 32 for c in result):
        raise ValueError("Invalid canonical identity")
    return result
