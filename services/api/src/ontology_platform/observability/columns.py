"""Column dependencies over the closed AST, checked against the actual Polars planner."""

from dataclasses import dataclass, field

import polars as pl

from ontology_platform.observability.contracts import ColumnDependency
from ontology_platform.pipelines.contracts import Definition, Expression, InputContract, Step
from ontology_platform.pipelines.engine import plan

Origin = tuple[str, str]


@dataclass
class FrameLineage:
    frame: pl.LazyFrame
    values: dict[str, set[Origin]]
    rows: set[Origin] = field(default_factory=set)
    order: set[Origin] = field(default_factory=set)


def referenced(expression: Expression | None) -> set[str]:
    if expression is None:
        return set()
    result = {expression.column} if expression.column else set()
    for arg in expression.args:
        result |= referenced(arg)
    return result


def apply(step: Step, left: FrameLineage, right: FrameLineage | None = None) -> FrameLineage:
    inputs = {"left": left.frame}
    contracts = [InputContract(name="left")]
    if right is not None:
        assert step.input is not None
        inputs[step.input] = right.frame
        contracts.append(InputContract(name=step.input))
    output = plan(Definition(inputs=contracts, steps=[step]), inputs)
    names = output.collect_schema().names()
    values = {k: set(v) for k, v in left.values.items()}
    rows, order = set(left.rows), set(left.order)

    def origins(columns: set[str]) -> set[Origin]:
        return set().union(*(left.values[c] for c in columns))

    if step.op == "rename":
        values = {step.mapping.get(k, k): v for k, v in values.items()}
    elif step.op == "derive":
        assert step.name is not None
        values[step.name] = origins(referenced(step.expression))
    elif step.op == "aggregate":
        groups = origins(set(step.columns))
        values = {c: values[c] for c in step.columns} | {
            a.alias: left.values[a.column] | groups for a in step.aggregates
        }
        rows |= groups
    elif step.op == "filter":
        rows |= origins(referenced(step.expression))
    elif step.op == "sort":
        order |= origins(set(step.columns))
    elif step.op == "deduplicate":
        rows |= origins(set(step.columns or left.values))
    elif step.op in {"join", "union"}:
        assert right is not None
        rows |= right.rows
        order |= right.order
        if step.op == "union":
            values = {c: v | right.values[c] for c, v in values.items()}
        else:
            rows |= origins(set(step.columns))
            rows |= set().union(*(right.values[c] for c in step.columns))
            for c in names:
                if c not in values:
                    values[c] = set(right.values[c])
                elif c in step.columns and step.how == "full":
                    # Full-join coalesced keys can originate on either side.
                    values[c] |= right.values[c]
    return FrameLineage(output, {c: values[c] for c in names}, rows, order)


def records(frame: FrameLineage, limit: int = 1000) -> tuple[list[ColumnDependency], bool]:
    result: list[ColumnDependency] = []
    for name in sorted(frame.values):
        for kind, origins in [
            ("VALUE", frame.values[name]),
            ("ROW", frame.rows),
            ("ORDER", frame.order),
        ]:
            for inp, column in sorted(origins):
                if len(result) >= limit:
                    return result, True
                result.append(
                    ColumnDependency(output=name, input_name=inp, input_column=column, kind=kind)
                )
    return result, False
