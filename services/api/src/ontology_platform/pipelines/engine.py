"""Polars adapter for portable specifications, using lazy plans and streaming sinks."""

import hashlib
import re
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import polars as pl
import polars.selectors as cs

from ontology_platform.datasets.parser import InvalidDataset
from ontology_platform.datasets.streaming import batches, validate_path
from ontology_platform.execution.config import ExecutionSettings
from ontology_platform.pipelines.contracts import Definition, Expression

TYPES: dict[str, pl.DataType | type[pl.DataType]] = {
    "String": pl.String,
    "Int64": pl.Int64,
    "UInt64": pl.UInt64,
    "Float64": pl.Float64,
    "Boolean": pl.Boolean,
    "Date": pl.Date,
    "Datetime": pl.Datetime("us"),
    "Decimal": pl.Decimal(38, 9),
}


def schema_dtype(value: str) -> pl.DataType | type[pl.DataType]:
    """Closed parser for committed scalar schema metadata; never evaluates type text."""
    scalars = TYPES | {
        "Null": pl.Null,
        "Int8": pl.Int8,
        "Int16": pl.Int16,
        "Int32": pl.Int32,
        "Int128": pl.Int128,
        "UInt8": pl.UInt8,
        "UInt16": pl.UInt16,
        "UInt32": pl.UInt32,
        "Float32": pl.Float32,
        "Time": pl.Time,
    }
    if value in scalars:
        return scalars[value]
    temporal = re.fullmatch(
        r"Datetime\(time_unit='(?P<unit>ns|us|ms)', time_zone=(?:None|'(?P<zone>[^']+)')\)", value
    )
    if temporal:
        return pl.Datetime(cast(Literal["ns", "us", "ms"], temporal["unit"]), temporal["zone"])
    decimal = re.fullmatch(r"Decimal\(precision=(None|[0-9]{1,2}), scale=([0-9]{1,2})\)", value)
    if decimal:
        precision = None if decimal[1] == "None" else int(decimal[1])
        scale = int(decimal[2])
        if 0 <= scale <= (precision or 38) and (precision is None or 1 <= precision <= 38):
            return pl.Decimal(precision, scale)
    raise InvalidDataset("Unsupported source schema type")


class ExecutionEngine(Protocol):
    name: str
    version: str

    def execute(
        self, request: dict[str, Any], directory: Path, limits: ExecutionSettings
    ) -> dict[str, Any]: ...


def expression(node: Expression, schema: pl.Schema | None = None) -> pl.Expr:
    if node.op == "column":
        assert node.column is not None
        if schema is not None and node.column not in schema:
            raise InvalidDataset("Missing expression column")
        return cs.by_name(node.column).as_expr()
    if node.op == "literal":
        return pl.lit(node.value)
    args = [expression(a, schema) for a in node.args]
    if node.op == "not":
        return ~args[0]
    if node.op == "is_null":
        return args[0].is_null()
    left, right = args
    if node.op == "coalesce":
        return pl.coalesce(left, right)
    if node.op in {"add", "subtract", "multiply"} and schema is not None:
        left_type = pl.LazyFrame(schema=schema).select(left).collect_schema().dtypes()[0]
        right_type = pl.LazyFrame(schema=schema).select(right).collect_schema().dtypes()[0]
        if left_type.is_integer() and right_type.is_integer():
            wide_left, wide_right = left.cast(pl.Decimal(38, 0)), right.cast(pl.Decimal(38, 0))
            wide = {
                "add": wide_left + wide_right,
                "subtract": wide_left - wide_right,
                "multiply": wide_left * wide_right,
            }[node.op]
            return wide.cast(
                pl.UInt64
                if left_type.is_unsigned_integer() and right_type.is_unsigned_integer()
                else pl.Int64,
                strict=True,
            )
    operations = {
        "add": lambda: left + right,
        "subtract": lambda: left - right,
        "multiply": lambda: left * right,
        "divide": lambda: left / right,
        "eq": lambda: left == right,
        "ne": lambda: left != right,
        "lt": lambda: left < right,
        "le": lambda: left <= right,
        "gt": lambda: left > right,
        "ge": lambda: left >= right,
        "and": lambda: left & right,
        "or": lambda: left | right,
    }
    return operations[node.op]()


def plan(spec: Definition, inputs: dict[str, pl.LazyFrame]) -> pl.LazyFrame:
    for contract in spec.inputs:
        schema = inputs[contract.name].collect_schema()
        for name, dtype in contract.columns.items():
            if name not in schema or str(schema[name]) != dtype:
                raise InvalidDataset("Input schema contract mismatch")
    frame = inputs[spec.inputs[0].name]
    for step in spec.steps:
        schema = frame.collect_schema()
        if any(c not in schema for c in step.columns + list(step.mapping)):
            raise InvalidDataset("Missing referenced column")
        if step.op == "select":
            frame = frame.select(cs.by_name(step.columns))
        elif step.op == "drop":
            frame = frame.drop(cs.by_name(step.columns))
        elif step.op == "rename":
            frame = frame.rename(step.mapping, strict=True)
        elif step.op == "filter":
            assert step.expression is not None
            frame = frame.filter(expression(step.expression, schema))
        elif step.op == "sort":
            frame = frame.sort(
                cs.by_name(step.columns), descending=step.descending, maintain_order=True
            )
        elif step.op == "cast":
            if any(t not in TYPES for t in step.mapping.values()):
                raise InvalidDataset("Unsupported cast type")
            frame = frame.with_columns(
                [
                    cs.by_name(c).as_expr().cast(TYPES[t], strict=True).alias(c)
                    for c, t in step.mapping.items()
                ]
            )
        elif step.op == "derive":
            assert step.expression is not None and step.name is not None
            if step.name in schema:
                raise InvalidDataset("Derived column collides with existing column")
            frame = frame.with_columns(expression(step.expression, schema).alias(step.name))
        elif step.op == "fill_null":
            assert step.name is not None
            if step.name not in schema:
                raise InvalidDataset("Missing fill column")
            frame = frame.with_columns(
                cs.by_name(step.name)
                .as_expr()
                .fill_null(pl.lit(step.value).cast(schema[step.name], strict=True))
            )
        elif step.op == "deduplicate":
            frame = frame.unique(
                subset=cs.by_name(step.columns) if step.columns else None, maintain_order=True
            )
        elif step.op == "aggregate":
            aggs = []
            for agg in step.aggregates:
                if agg.column not in schema:
                    raise InvalidDataset("Missing aggregate column")
                column = cs.by_name(agg.column).as_expr()
                if agg.function == "sum" and schema[agg.column].is_integer():
                    aggregate = (
                        column.cast(pl.Decimal(38, 0)).sum().cast(schema[agg.column], strict=True)
                    )
                else:
                    aggregate = getattr(column, agg.function)()
                aggs.append(aggregate.alias(agg.alias))
            frame = frame.group_by(cs.by_name(step.columns), maintain_order=True).agg(aggs)
        elif step.op == "join":
            assert step.input is not None
            right = inputs[step.input]
            right_schema = right.collect_schema()
            if any(c not in right_schema or schema[c] != right_schema[c] for c in step.columns):
                raise InvalidDataset("Incompatible join keys")
            if (set(schema) & set(right_schema)) - set(step.columns):
                raise InvalidDataset("Join output column collision; rename inputs first")
            # Internal literal join keys avoid Polars interpreting unusual user names as regex.
            used = set(schema) | set(right_schema)
            internal = {}
            index = 0
            for key in step.columns:
                while f"__foundry_join_{index}" in used:
                    index += 1
                internal[key] = f"__foundry_join_{index}"
                used.add(internal[key])
            frame = (
                frame.rename(internal)
                .join(
                    right.rename(internal),
                    on=list(internal.values()),
                    how=step.how,
                    coalesce=True,
                    maintain_order="left_right",
                )
                .rename({v: k for k, v in internal.items()})
            )

        elif step.op == "union":
            assert step.input is not None
            if schema != inputs[step.input].collect_schema():
                raise InvalidDataset("Union schemas must match exactly")
            frame = pl.concat([frame, inputs[step.input]], how="vertical")
        # Reject missing columns, collisions and incompatible types during planning.
        frame.collect_schema()
    output = frame.collect_schema()
    if spec.output_columns and {k: str(v) for k, v in output.items()} != spec.output_columns:
        raise InvalidDataset("Output schema contract mismatch")
    return frame


class PolarsEngine:
    name = "polars"
    version = pl.__version__

    def execute(
        self, request: dict[str, Any], directory: Path, limits: ExecutionSettings
    ) -> dict[str, Any]:
        spec = Definition.model_validate(request["specification"])
        inputs = {}
        for item in request["inputs"]:
            path = Path(item["path"])
            # Normalize text to bounded Parquet pieces; never infer only an initial sample.
            if item["format"] != "parquet":
                import pyarrow.parquet as pq  # type: ignore[import-untyped]

                source_schema = validate_path(path, item["format"], limits)
                if item["format"] == "csv":
                    csv_types: dict[str, pl.DataType | type[pl.DataType]] = {
                        **TYPES,
                        "Time": pl.Time,
                        "Int128": pl.Int128,
                        "Null": pl.String,
                        "Datetime(time_unit='us', time_zone=None)": pl.Datetime("us"),
                        "Datetime(time_unit='us', time_zone='UTC')": pl.Datetime("us", "UTC"),
                    }
                    overrides = {
                        c["name"]: csv_types[c["logical_type"]] for c in source_schema["schema"]
                    }
                    inputs[item["name"]] = pl.scan_csv(
                        path, schema_overrides=overrides, infer_schema=False, try_parse_dates=True
                    )
                    continue
                reconciled = None
                for batch in batches(path, item["format"], limits):
                    reconciled = (
                        batch.clear()
                        if reconciled is None
                        else pl.concat([reconciled, batch.clear()], how="vertical_relaxed")
                    )
                parts = directory / ("normalized-" + str(len(inputs)))
                parts.mkdir()
                for i, frame in enumerate(batches(path, item["format"], limits)):
                    assert reconciled is not None
                    pq.write_table(
                        frame.cast(reconciled.schema).to_arrow(), parts / f"{i:08}.parquet"
                    )
                if not list(parts.iterdir()):
                    raise InvalidDataset("Empty text input has no executable schema")
                inputs[item["name"]] = pl.scan_parquet(
                    str(parts / "*.parquet"), missing_columns="raise"
                )
                del source_schema
            else:
                inputs[item["name"]] = pl.scan_parquet(path, use_statistics=False)
        for item in request["inputs"]:
            expected = item.get("schema")
            actual = inputs[item["name"]].collect_schema()
            if expected is not None and [(c["name"], c["logical_type"]) for c in expected] != [
                (name, str(dtype)) for name, dtype in actual.items()
            ]:
                raise InvalidDataset("Input logical schema differs from its immutable snapshot")
            if item.get("row_count") is not None:
                count = inputs[item["name"]].select(pl.len()).collect(engine="streaming").item()
                if count != item["row_count"]:
                    raise InvalidDataset("Input row count differs from its immutable snapshot")
        lazy = plan(spec, inputs)
        output_format = request.get("output_format", "parquet")
        output = directory / ("output." + output_format)
        if output_format == "parquet":
            lazy.sink_parquet(output, row_group_size=8192, maintain_order=True, engine="streaming")
        elif output_format == "csv":
            lazy.sink_csv(output, maintain_order=True, engine="streaming")
        elif output_format == "ndjson":
            lazy.sink_ndjson(output, maintain_order=True, engine="streaming")
        else:
            raise InvalidDataset("Unsupported output format")
        result = validate_path(output, output_format, limits)
        if [(c["name"], c["logical_type"]) for c in result["schema"]] != [
            (name, str(dtype)) for name, dtype in lazy.collect_schema().items()
        ]:
            raise InvalidDataset("Materialization changed the planned logical schema")
        digest = hashlib.sha256()
        with output.open("rb") as file:
            while chunk := file.read(65536):
                digest.update(chunk)
        return {
            "dataset": result,
            "size": output.stat().st_size,
            "checksum": digest.hexdigest(),
            "engine": self.name,
            "engine_version": self.version,
        }


def dag_frames(
    spec: Any, inputs: dict[str, pl.LazyFrame], *, schema_only: bool = False
) -> dict[str, pl.LazyFrame]:
    """Schema propagation uses the same operation adapter as legacy execution."""
    from ontology_platform.pipelines.contracts import InputContract
    from ontology_platform.pipelines.dag import topology

    frames = dict(inputs)
    for contract in spec.inputs:
        plan(
            Definition(inputs=[InputContract(name=contract.name, columns=contract.columns)]), frames
        )
    nodes = {node.id: node for node in spec.nodes}
    for key in topology(spec):
        node = nodes[key]
        bindings = {port: frames[source] for port, source in node.inputs.items()}
        frames[key] = plan(
            Definition(
                inputs=[
                    InputContract(name=port) for port in ["input", "right"] if port in bindings
                ],
                steps=[node.config],
            ),
            bindings,
        )
        if schema_only:
            # Schema-only planning must not retain exponentially nested branch plans.
            frames[key] = pl.LazyFrame(schema=frames[key].collect_schema())
    for output in spec.outputs:
        schema = {
            name: str(dtype) for name, dtype in frames[output.source].collect_schema().items()
        }
        if output.columns and output.columns != schema:
            raise InvalidDataset("Output schema contract mismatch")
    return frames
