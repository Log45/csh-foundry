"""One bounded deterministic compiler used by the API and CLI; canonical models are inputs."""

import hashlib
import io
import json
import keyword
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ontology_schema.models import OntologyDefinition, PropertyDefinition
from pydantic import BaseModel

from ontology_platform.branching.service import bounded, hash_payload
from ontology_platform.errors import ApplicationError
from ontology_platform.metadata.storage import digest

GENERATOR_VERSION = "9.0.0"
Language = Literal["python", "typescript"]
TEMPLATES = Path(__file__).parent / "templates"
RESERVED = set(keyword.kwlist) | set(
    "await break case catch class const continue debugger default delete do else enum export extends false finally for function if import in instanceof interface let new null return super switch this throw true try typeof var void while with yield implements private protected public static package constructor prototype __proto__ actions transport close fields query create get patch delete model_config model_fields".split()  # noqa: E501 - emitted source template
)

RESERVED |= set(dir(BaseModel)) | set(
    "date datetime Decimal UUID JsonValue Literal ModelField Any Properties validate_wire".split()
)


def symbol(value: str) -> str:
    if (
        re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value)
        and value not in RESERVED
        and not value.startswith("model_")
    ):
        return value
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value)[:60]
    return "v_" + cleaned + "_" + hashlib.sha256(value.encode()).hexdigest()[:10]


def symbols(values: list[str]) -> dict[str, str]:
    if len(values) != len(set(values)):
        raise ApplicationError(
            "sdk_name_collision", "Duplicate symbols in generated namespace", 422
        )
    result = {value: symbol(value) for value in sorted(values)}
    if len(set(result.values())) != len(result):
        raise ApplicationError("sdk_name_collision", "Ambiguous generated identifiers", 422)
    return result


def literal(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def py_type(prop: PropertyDefinition) -> str:
    types = {
        "string": "str",
        "integer": "int",
        "float": "float",
        "boolean": "bool",
        "date": "date",
        "timestamp": "datetime",
        "uuid": "UUID",
        "decimal": "Decimal",
        "json": "JsonValue",
    }
    result = types[prop.data_type]
    if prop.enum and all(isinstance(v, (str, int, bool)) for v in prop.enum):
        result = "Literal[" + ", ".join(repr(v) for v in prop.enum) + "]"
    if prop.array:
        result = "list[" + result + "]"
    return result


def ts_type(prop: PropertyDefinition) -> str:
    result = {
        "string": "string",
        "integer": "number",
        "float": "number",
        "boolean": "boolean",
        "date": "string",
        "timestamp": "string",
        "uuid": "string",
        "decimal": "string",
        "json": "Json",
    }[prop.data_type]
    if prop.enum:
        result = " | ".join(literal(v) for v in prop.enum)
    if prop.array:
        result = "(" + result + ")[]"
    if prop.nullable:
        result += " | null"
    return result


def field_class(prop: PropertyDefinition) -> str:
    if prop.array:
        return "Field"
    if prop.data_type == "string" and not prop.enum:
        return "TextField"
    if prop.data_type in {"integer", "float", "decimal", "date", "timestamp"}:
        return "OrderedField"
    return "Field"


def python_model(name: str, properties: tuple[PropertyDefinition, ...], *, required: bool) -> str:
    lines = [f"class {name}(Properties):"]
    aliases = symbols([p.id for p in properties])
    nullable: list[str] = []
    for prop in sorted(properties, key=lambda p: p.id):
        nullable += [prop.id] if prop.nullable else []
        typename = py_type(prop)
        mandatory = (
            required and prop.required and not (prop.has_default or prop.default is not None)
        )
        if prop.nullable or not mandatory:
            typename += " | None"
        options = [f"alias={prop.id!r}"]
        # Strict scalar primitives; dates, decimals and UUIDs accept their canonical wire strings.
        if (
            prop.data_type in {"string", "integer", "float", "boolean"}
            and not prop.array
            and not prop.enum
        ):
            options.append("strict=True")
        if prop.max_length is not None and not prop.array:
            options.append(f"max_length={prop.max_length}")
        if prop.data_type == "decimal" and not prop.array:
            options += [f"max_digits={prop.precision}", f"decimal_places={prop.scale}"]
        default = "..." if mandatory else "None"
        lines.append(
            f"    {aliases[prop.id]}: {typename} = ModelField({default}, {', '.join(options)})"
        )
    if not properties:
        lines.append("    pass")
    else:
        lines += [
            "",
            "    @model_validator(mode='before')",
            "    @classmethod",
            "    def validate_wire(cls, value: Any) -> Any:",
            "        if isinstance(value, dict):",
        ]
        for prop in sorted(properties, key=lambda p: p.id):
            alias = aliases[prop.id]
            lines += [
                f"            key = {prop.id!r} if {prop.id!r} in value else {alias!r}",
                "            if key in value:",
            ]
            if not prop.nullable:
                lines += [
                    "                if value[key] is None:",
                    "                    raise ValueError('Nonnullable property cannot be null')",
                ]
            if prop.data_type == "decimal":
                lines += [
                    "                values = value[key] if isinstance(value[key], list) else [value[key]]",  # noqa: E501 - emitted source template
                    "                if any(v is not None and not isinstance(v, (str, Decimal)) for v in values):",  # noqa: E501 - emitted source template
                    "                    raise ValueError('Decimals require strings or Decimal')",
                ]
            if prop.data_type == "timestamp":
                lines += [
                    "                values = value[key] if isinstance(value[key], list) else [value[key]]",  # noqa: E501 - emitted source template
                    "                for item in values:",
                    "                    if item is not None:",
                    "                        parsed = datetime.fromisoformat(item) if isinstance(item, str) else item",  # noqa: E501 - emitted source template
                    "                        if not isinstance(parsed, datetime) or parsed.utcoffset() is None:",  # noqa: E501 - emitted source template
                    "                            raise ValueError('Timestamp requires timezone')",
                ]
            lines += ["                pass"]
        lines += ["        return value"]
    return "\n".join(lines) + "\n\n"


def python_files(schema: OntologyDefinition) -> dict[str, str]:
    object_symbols = symbols([o.id for o in schema.object_types])
    action_symbols = symbols([a.id for a in schema.action_types])
    models = """from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from typing import Any, Literal
from pydantic import Field as ModelField, JsonValue, model_validator
from .runtime import Properties

"""
    client = """from __future__ import annotations
import httpx
from .runtime import (Action, Field, OrderedField, TextField, ObjectSet,
                      Repository, TokenProvider, Transport)
from .models import *

"""
    for obj in sorted(schema.object_types, key=lambda o: o.id):
        name = object_symbols[obj.id]
        for suffix, required in (("Properties", False), ("Create", True), ("Patch", False)):
            models += python_model(name + suffix, obj.properties, required=required)
        client += f"class {name}Fields:\n"
        for prop in sorted(obj.properties, key=lambda p: p.id):
            cls, alias = field_class(prop), symbol(prop.id)
            typename = py_type(prop)
            typeargs = "" if cls == "TextField" else f"[{typename}]"
            client += f"    {alias} = {cls}{typeargs}({prop.id!r})\n"
        if not obj.properties:
            client += "    pass\n"
        client += f"\nclass {name}Repository(Repository[{name}Properties, {name}Create, {name}Patch]):\n    fields = {name}Fields()\n"  # noqa: E501 - emitted source template
        links: list[tuple[str, str, bool]] = []
        for link in schema.link_types:
            if link.source_type == obj.id:
                links.append((link.id, link.target_type, False))
            if link.target_type == obj.id:
                links.append((link.inverse_name or link.id, link.source_type, True))
        link_aliases = symbols([link[0] for link in links])
        for link_id, target, inverse in sorted(links):
            pk = next(p for p in obj.properties if p.id == obj.primary_key)
            identity_value = (
                "int(object_id)"
                if pk.data_type == "integer"
                else "UUID(object_id)"
                if pk.data_type == "uuid"
                else "object_id"
            )
            client += (
                f"\n    def related_{link_aliases[link_id]}(self, object_id: str) -> ObjectSet[{object_symbols[target]}Properties]:\n"  # noqa: E501 - emitted source template
                f"        return self.query().where(self.fields.{symbol(pk.id)}.eq({identity_value})).traverse({link_id!r}, {object_symbols[target]}Properties, inverse={inverse!r})\n"  # noqa: E501 - emitted source template
            )
        client += "\n"
    client += "class Actions:\n    def __init__(self, transport: Transport):\n"
    for action in sorted(schema.action_types, key=lambda a: a.id):
        name = action_symbols[action.id]
        models += python_model(name + "Parameters", action.parameters, required=True)
        client += f"        self.{name} = Action(transport, {action.id!r}, {name}Parameters)\n"
    if not schema.action_types:
        client += "        pass\n"
    client += (
        "\nclass OntologyClient:\n"
        "    def __init__(self, base_url: str, token_provider: TokenProvider, tenant_id: str, *, http: httpx.AsyncClient | None = None):\n"  # noqa: E501 - emitted source template
        f"        self.transport = Transport(base_url, token_provider, tenant_id, {schema.id!r}, {schema.version!r}, http)\n"  # noqa: E501 - emitted source template
        "        self.actions = Actions(self.transport)\n"
    )
    for obj in sorted(schema.object_types, key=lambda o: o.id):
        name = object_symbols[obj.id]
        client += f"        self.{name} = {name}Repository(self.transport, {obj.id!r}, {name}Properties, {name}Create, {name}Patch)\n"  # noqa: E501 - emitted source template
    client += "\n    async def close(self) -> None:\n        await self.transport.close()\n"
    # Generated field type annotations need these public standard-library imports.
    client = client.replace(
        "import httpx",
        "import httpx\nfrom datetime import date, datetime\nfrom decimal import Decimal\nfrom uuid import UUID\nfrom typing import Literal\nfrom pydantic import JsonValue",  # noqa: E501 - emitted source template
    )
    return {
        "ontology_sdk/models.py": models,
        "ontology_sdk/client.py": client,
        "ontology_sdk/runtime.py": (TEMPLATES / "runtime.py.txt").read_text(),
        "ontology_sdk/__init__.py": "from .client import OntologyClient as OntologyClient\nfrom .runtime import SDKError as SDKError\n",  # noqa: E501 - emitted source template
        "ontology_sdk/py.typed": "",
        "pyproject.toml": f'''[project]
name = "ontology-generated-sdk"
version = "{schema.version}"
requires-python = ">=3.12"
dependencies = ["httpx==0.28.1", "pydantic==2.14.1"]
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
[tool.hatch.build.targets.wheel]
packages = ["ontology_sdk"]
''',
    }


def typescript_files(schema: OntologyDefinition) -> dict[str, str]:
    objs = symbols([o.id for o in schema.object_types])
    acts = symbols([a.id for a in schema.action_types])
    output = 'import {Action, Field, OrderedField, TextField, ObjectSet, Repository, Transport, type ClientOptions, type Json} from "./runtime.js";\nexport * from "./runtime.js";\n'  # noqa: E501 - emitted source template
    for obj in sorted(schema.object_types, key=lambda o: o.id):
        name = objs[obj.id]
        for suffix, required in (("Properties", False), ("Create", True), ("Patch", False)):
            output += f"export interface {name}{suffix} {{\n"
            for prop in sorted(obj.properties, key=lambda p: p.id):
                mandatory = (
                    required
                    and prop.required
                    and not (prop.has_default or prop.default is not None)
                )
                output += f"  {literal(prop.id)}{'' if mandatory else '?'}: {ts_type(prop)};\n"
            output += "}\n"
        output += f"export class {name}Repository extends Repository<{name}Properties, {name}Create, {name}Patch> {{\n  readonly fields = {{\n"  # noqa: E501 - emitted source template
        for prop in sorted(obj.properties, key=lambda p: p.id):
            cls = field_class(prop)
            typeargs = (
                "" if cls == "TextField" else "<" + ts_type(prop).replace(" | null", "") + ">"
            )
            output += f"    {literal(symbol(prop.id))}: new {cls}{typeargs}({literal(prop.id)}),\n"
        output += "  };\n"
        links = []
        for link in schema.link_types:
            if link.source_type == obj.id:
                links.append((link.id, link.target_type, False))
            if link.target_type == obj.id:
                links.append((link.inverse_name or link.id, link.source_type, True))
        symbols([v[0] for v in links])
        for link_id, target, inverse in sorted(links):
            pk = next(p for p in obj.properties if p.id == obj.primary_key)
            key = "Number(objectId)" if pk.data_type == "integer" else "objectId"
            output += f"  related_{symbol(link_id)}(objectId: string): ObjectSet<{objs[target]}Properties> {{ return this.query().where(new Field<{ts_type(pk)}>({literal(pk.id)}).eq({key})).traverse<{objs[target]}Properties>({literal(link_id)}, {str(inverse).lower()}); }}\n"  # noqa: E501 - emitted source template
        output += "}\n"
    output += "export class Actions {\n"
    for action in sorted(schema.action_types, key=lambda a: a.id):
        output += f"  readonly {acts[action.id]}: Action<{acts[action.id]}Parameters>;\n"
    output += "  constructor(transport: Transport) {\n"
    for action in sorted(schema.action_types, key=lambda a: a.id):
        output += f"    this.{acts[action.id]} = new Action(transport, {literal(action.id)});\n"
    output += "  }\n}\n"
    for action in sorted(schema.action_types, key=lambda a: a.id):
        output += f"export interface {acts[action.id]}Parameters {{\n"
        for prop in sorted(action.parameters, key=lambda p: p.id):
            output += f"  {literal(prop.id)}{'' if prop.required and not (prop.has_default or prop.default is not None) else '?'}: {ts_type(prop)};\n"  # noqa: E501 - emitted source template
        output += "}\n"
    output += "export class OntologyClient {\n  readonly transport: Transport;\n  readonly actions: Actions;\n"  # noqa: E501 - emitted source template
    for obj in sorted(schema.object_types, key=lambda o: o.id):
        output += f"  readonly {objs[obj.id]}: {objs[obj.id]}Repository;\n"
    output += f"  constructor(options: ClientOptions) {{\n    this.transport = new Transport(options, {literal(schema.id)}, {literal(schema.version)});\n    this.actions = new Actions(this.transport);\n"  # noqa: E501 - emitted source template
    for obj in sorted(schema.object_types, key=lambda o: o.id):
        output += f"    this.{objs[obj.id]} = new {objs[obj.id]}Repository(this.transport, {literal(obj.id)});\n"  # noqa: E501 - emitted source template
    output += "  }\n}\n"
    return {
        "src/index.ts": output,
        "src/runtime.ts": (TEMPLATES / "runtime.ts.txt").read_text(),
        "package.json": json.dumps(
            {
                "name": "@ontology/generated-sdk",
                "version": schema.version,
                "type": "module",
                "exports": {".": {"types": "./dist/index.d.ts", "import": "./dist/index.js"}},
                "files": ["dist", "manifest.json", "schema.json"],
                "scripts": {"build": "tsc -p tsconfig.json"},
                "devDependencies": {"typescript": "5.9.3"},
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        "tsconfig.json": json.dumps(
            {
                "compilerOptions": {
                    "strict": True,
                    "target": "ES2022",
                    "module": "NodeNext",
                    "moduleResolution": "NodeNext",
                    "declaration": True,
                    "outDir": "dist",
                    "noUncheckedIndexedAccess": True,
                },
                "include": ["src/**/*.ts"],
            },
            indent=2,
        )
        + "\n",
    }


@dataclass(frozen=True)
class Generated:
    files: dict[str, str]
    manifest: dict[str, Any]

    def archive(self) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, value in sorted(self.files.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, value.encode())
        return buffer.getvalue()


def generate(
    schema: OntologyDefinition, language: Language, api_contract: dict[str, Any]
) -> Generated:
    bounded(schema)
    if language not in {"python", "typescript"}:
        raise ApplicationError("unsupported_language", "Choose python or typescript", 422)
    required = {
        "/api/v1/ontologies/{ontology_id}/objects/{type_id}": {"get", "post", "patch", "delete"},
        "/api/v1/ontologies/{ontology_id}/object-sets/query": {"post"},
        "/api/v1/ontologies/{ontology_id}/aggregate": {"post"},
        "/api/v1/ontologies/{ontology_id}/actions/{action_id}/preview": {"post"},
        "/api/v1/ontologies/{ontology_id}/actions/{action_id}/execute": {"post"},
    }
    for path, methods in required.items():
        if not methods <= api_contract.get("paths", {}).get(path, {}).keys():
            raise ApplicationError(
                "unsupported_api_contract", "Required SDK operation is absent", 422
            )
    required_shapes = {
        "QueryRequest": {
            "object_type",
            "filter",
            "traverse",
            "result_filter",
            "pagination",
            "order_by",
            "select",
            "limit",
            "offset",
            "cursor",
        },
        "QueryPage": {"object_type", "schema_version", "items", "next_cursor", "has_more"},
        "ObjectPatch": {"expected_version", "properties"},
        "ExecuteRequest": {"parameters", "idempotency_key"},
        "ActionResult": {
            "execution_id",
            "action_id",
            "action_version",
            "schema_version",
            "changes",
            "advisory",
        },
    }
    schemas = api_contract.get("components", {}).get("schemas", {})
    for name, properties in required_shapes.items():
        if not properties <= schemas.get(name, {}).get("properties", {}).keys():
            raise ApplicationError(
                "unsupported_api_contract", "Required SDK transport shape changed", 422
            )
    files = python_files(schema) if language == "python" else typescript_files(schema)
    files["schema.json"] = schema.canonical_json() + "\n"
    files["README.md"] = (
        f"# Generated {schema.id} SDK\n\nPublished version {schema.version}; canonical hash {digest(schema)}.\n"  # noqa: E501 - emitted source template
        "All requests require a caller-supplied async platform bearer token provider and tenant ID.\n"  # noqa: E501 - emitted source template
        "No token is stored in this package. Queries target the active server schema; mismatched versions fail.\n"  # noqa: E501 - emitted source template
        "Decimal values use exact strings (TypeScript) or Decimal/string inputs (Python).\n"
        "Read properties are optional because authorization and projection may omit fields.\n"
        "Cursor pages are current reads, not snapshots. Retry actions with the same caller-supplied idempotency key.\n"  # noqa: E501 - emitted source template
        "Publication and activation are separate server governance operations.\n"
    )
    manifest: dict[str, Any] = {
        "tenant_id": str(schema.tenant_id),
        "ontology_id": schema.id,
        "schema_version": schema.version,
        "schema_hash": digest(schema),
        "api_contract_hash": hash_payload(api_contract),
        "generator_version": GENERATOR_VERSION,
        "language": language,
        "generation_timestamp": "1980-01-01T00:00:00Z",
        "timestamp_policy": "reproducible epoch; issuance time stored separately",
        "symbols": {
            "objects": symbols([o.id for o in schema.object_types]),
            "actions": symbols([a.id for a in schema.action_types]),
        },
        "files": {
            name: hashlib.sha256(value.encode()).hexdigest()
            for name, value in sorted(files.items())
        },
    }
    # The manifest cannot hash itself. Hash the sorted source/file digest map and record archive
    # hashes separately on issuance. Both are deterministic and independently verifiable.
    manifest["artifact_content_hash"] = hash_payload(manifest["files"])
    files["manifest.json"] = (
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    )
    if sum(len(value.encode()) for value in files.values()) > 4 * 1024 * 1024:
        raise ApplicationError("sdk_too_large", "Generated SDK exceeds 4 MiB", 422)
    return Generated(dict(sorted(files.items())), manifest)
