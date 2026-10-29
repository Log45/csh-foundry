"""Server-owned tenant connector allowlist; never populated from execution bodies."""

import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr

from ontology_platform.contracts import APIModel
from ontology_platform.errors import ApplicationError
from ontology_platform.ingestion.contracts import Kind


class InputColumn(APIModel):
    name: str = Field(max_length=200)
    data_type: Literal[
        "string", "integer", "float", "boolean", "date", "timestamp", "decimal", "uuid"
    ] = "string"
    nullable: bool = False


class Binding(APIModel):
    tenant_id: UUID
    key: str
    revision: str = "1"
    kind: Kind
    columns: list[InputColumn] = Field(min_length=1, max_length=64)
    source_key_column: str
    root: str | None = None
    file_name: str | None = None
    delimiter: str = Field(default=",", min_length=1, max_length=1)
    url: SecretStr | None = None
    table_schema: str = "public"
    table: str | None = None
    equals: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=8)

    def path(self) -> Path:
        if not self.root or not self.file_name:
            raise ApplicationError("source_unavailable", "File registration is incomplete", 422)
        root = Path(self.root).resolve()
        path = (root / self.file_name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ApplicationError(
                "source_path_denied", "Source is outside its registered root", 403
            )
        return path


class SourceCatalog:
    def __init__(self, bindings: list[Binding] | None = None):
        self.bindings = {(b.tenant_id, b.key): b for b in bindings or []}
        if len(self.bindings) != len(bindings or []):
            raise ValueError("Duplicate server registrations")

    @classmethod
    def from_json(cls, value: SecretStr | None) -> "SourceCatalog":
        try:
            return (
                cls([Binding.model_validate(b) for b in json.loads(value.get_secret_value())])
                if value
                else cls()
            )
        except (ValueError, TypeError):
            raise ValueError("Invalid server ingestion catalog") from None

    def get(self, tenant: UUID, key: str) -> Binding:
        binding = self.bindings.get((tenant, key))
        if binding is None:
            raise ApplicationError(
                "source_not_registered", "Source is not registered for this tenant", 403
            )
        names = [c.name for c in binding.columns]
        if len(names) != len(set(names)) or binding.source_key_column not in names:
            raise ApplicationError("invalid_registration", "Invalid registered source columns", 422)
        if not set(binding.equals) <= set(names):
            raise ApplicationError("invalid_registration", "Filter column is not registered", 422)
        for name, value in binding.equals.items():
            column = next(c for c in binding.columns if c.name == name)
            expected = {"integer": int, "float": float, "boolean": bool}.get(column.data_type, str)
            if value is not None and type(value) is not expected:
                raise ApplicationError(
                    "invalid_registration", "Filter value differs from registered type", 422
                )
        if binding.kind == "csv" and any(c.data_type != "string" for c in binding.columns):
            raise ApplicationError(
                "invalid_registration",
                "CSV columns use strings and explicit mapping conversions",
                422,
            )
        return binding
