from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.db.governance import GovernedService
from ontology_platform.db.models import Object
from ontology_platform.errors import ApplicationError
from ontology_platform.metadata.storage import active_definition
from ontology_platform.queries.ast import (
    MAX_SELECT,
    AggregateGroup,
    AggregateRequest,
    AggregateResult,
    AggregateValue,
    QueryObject,
    QueryPage,
    QueryRequest,
)
from ontology_platform.queries.compiler import (
    NUMERIC,
    SORTABLE,
    Expression,
    QueryCompiler,
    invalid,
    seek_after,
)
from ontology_platform.queries.cursor import CursorCodec, fingerprint
from ontology_platform.security.interfaces import Authorizer, Principal


def serial(value: Any) -> Any:
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


class QueryService(GovernedService):
    def __init__(
        self,
        sessions: sessionmaker[Session],
        authorizer: Authorizer,
        cursors: CursorCodec | None = None,
        *,
        session: Session | None = None,
    ):
        super().__init__(sessions, authorizer, session=session)
        self.cursors = cursors or CursorCodec()

    def query(self, principal: Principal, ontology_id: str, request: QueryRequest) -> QueryPage:
        request = QueryRequest.model_validate(request.model_dump(mode="json", by_alias=True))
        try:
            with self.operation(principal, "object:query", f"{ontology_id}/queries") as session:
                ontology = self.ontology(session, principal, ontology_id)
                schema = active_definition(session, ontology)
                compiler = QueryCompiler(schema, principal, self.authorizer)
                final_type, ids = compiler.object_set(request)
                sort = compiler.sorting(final_type, request.order_by)
                typed = next(t for t in schema.object_types if t.id == final_type)
                visible = compiler.grant(final_type).visible_properties
                selected = (
                    request.select
                    if request.select is not None
                    else tuple(p.id for p in typed.properties if visible is None or p.id in visible)
                )
                if len(selected) > MAX_SELECT:
                    raise invalid("Select at most 32 properties explicitly")
                for name in selected:
                    compiler.prop(final_type, name)
                binding = {
                    "tenant": str(principal.tenant_id),
                    "principal": principal.principal_id,
                    "actor": principal.actor_id,
                    "ontology": ontology_id,
                    "object_type": request.object_type,
                    "schema": schema.version,
                    "query": fingerprint(
                        request.model_dump(mode="json", by_alias=True, exclude={"cursor"})
                    ),
                    "policy": self.cursors.bind(
                        {
                            name: g.model_dump(mode="json", by_alias=True)
                            for name, g in compiler.grants.items()
                        },
                        purpose="policy",
                    ),
                }
                sorts = [expr.label(f"sort_{i}") for i, (expr, _) in enumerate(sort)]
                base = select(Object.object_id, Object.version, *sorts).where(
                    Object.object_id.in_(ids), compiler.scope(Object, final_type)
                )
                after = None
                if request.cursor is not None:
                    token = self.cursors.decode(request.cursor)
                    if any(
                        token.get(key) != binding[key]
                        for key in ("tenant", "principal", "ontology", "object_type")
                    ):
                        raise ApplicationError(
                            "invalid_cursor", "Cursor belongs to another context", 400
                        )
                    if token.get("schema") != schema.version:
                        raise ApplicationError(
                            "cursor_schema_changed",
                            "Active schema changed; restart pagination",
                            409,
                        )
                    if any(token.get(key) != value for key, value in binding.items()):
                        raise ApplicationError(
                            "invalid_cursor", "Cursor does not match query or authorization", 400
                        )
                    if not isinstance(token.get("anchor"), str):
                        raise ApplicationError("invalid_cursor", "Invalid cursor anchor", 400)
                    anchor = session.execute(
                        base.where(Object.object_id == token["anchor"])
                    ).first()
                    if anchor is None or anchor.version != token.get("revision"):
                        raise ApplicationError(
                            "cursor_stale", "Cursor anchor changed; restart pagination", 409
                        )
                    values = [anchor._mapping[f"sort_{i}"] for i in range(len(sort))]
                    if self.cursors.bind(
                        [serial(v) for v in values], purpose="sort-values"
                    ) != token.get("values_hash"):
                        raise ApplicationError(
                            "cursor_stale", "Cursor anchor changed; restart pagination", 409
                        )
                    after = seek_after(sort, values)
                columns = [
                    Object.tenant_id,
                    Object.ontology_id,
                    Object.object_type_id,
                    Object.object_id,
                    Object.schema_version,
                    Object.version,
                    Object.created_at,
                    Object.updated_at,
                    *sorts,
                ]
                for i, name in enumerate(selected):
                    # Individual SQL keys only: never fetch complete JSONB and redact afterward.
                    columns.extend(
                        [
                            Object.properties[name].label(f"p_{i}"),
                            Object.properties.has_key(name).label(f"has_{i}"),
                        ]
                    )
                statement = select(*columns).where(
                    Object.object_id.in_(ids), compiler.scope(Object, final_type)
                )
                if after is not None:
                    statement = statement.where(after)
                for expression, desc in sort:
                    statement = statement.order_by(
                        (expression.desc() if desc else expression.asc()).nulls_last()
                    )
                rows = session.execute(
                    statement.limit(request.limit + 1).offset(request.offset)
                ).all()
                more = len(rows) > request.limit
                rows = rows[: request.limit]
                items = []
                for row in rows:
                    data = row._mapping
                    props = {
                        name: data[f"p_{i}"] for i, name in enumerate(selected) if data[f"has_{i}"]
                    }
                    items.append(
                        QueryObject(
                            tenant_id=data["tenant_id"],
                            ontology_id=data["ontology_id"],
                            object_type_id=data["object_type_id"],
                            object_id=data["object_id"],
                            schema_version=data["schema_version"],
                            version=data["version"],
                            created_at=data["created_at"],
                            updated_at=data["updated_at"],
                            properties=props,
                        )
                    )
                cursor = None
                if more and rows and not request.offset and request.pagination == "cursor":
                    last = rows[-1]._mapping
                    cursor = self.cursors.encode(
                        binding
                        | {
                            "anchor": last["object_id"],
                            "revision": last["version"],
                            "values_hash": self.cursors.bind(
                                [serial(last[f"sort_{i}"]) for i in range(len(sort))],
                                purpose="sort-values",
                            ),
                        }
                    )
                return QueryPage(
                    object_type=final_type,
                    schema_version=schema.version,
                    items=items,
                    next_cursor=cursor,
                    has_more=more,
                )
        except DBAPIError as exc:
            code = getattr(exc.orig, "sqlstate", "")
            if code in {"57014", "55P03"}:
                raise ApplicationError(
                    "query_timeout", "Query exceeded the database time budget", 503
                ) from exc
            raise ApplicationError(
                "query_execution_failed", "Query could not be executed", 422
            ) from exc

    def aggregate(
        self, principal: Principal, ontology_id: str, request: AggregateRequest
    ) -> AggregateResult:
        request = AggregateRequest.model_validate(request.model_dump(mode="json", by_alias=True))
        try:
            with self.operation(principal, "object:aggregate", f"{ontology_id}/queries") as session:
                ontology = self.ontology(session, principal, ontology_id)
                schema = active_definition(session, ontology)
                compiler = QueryCompiler(schema, principal, self.authorizer)
                final_type, ids = compiler.object_set(request)
                expressions = []
                result_types = []
                group = None
                group_type = None
                if request.group_by is not None:
                    prop = compiler.prop(final_type, request.group_by)
                    if prop.array or prop.data_type not in SORTABLE:
                        raise invalid("Grouping requires a sortable scalar property")
                    group = compiler.value(Object, final_type, prop)
                    group_type = prop.data_type
                for i, metric in enumerate(request.metrics):
                    expr = None
                    kind = "integer"
                    if metric.property is not None:
                        prop = compiler.prop(final_type, metric.property)
                        kind = prop.data_type
                        if metric.operator != "count" and (prop.array or kind == "json"):
                            raise invalid("Aggregate requires a compatible scalar property")
                        if metric.operator in {"sum", "avg"} and kind not in NUMERIC:
                            raise invalid("Sum/average require numeric properties")
                        if metric.operator in {"min", "max"} and kind not in NUMERIC | {
                            "string",
                            "date",
                            "timestamp",
                        }:
                            raise invalid("Min/max require numeric, string or temporal properties")
                        # count(property) excludes missing AND explicit null even for JSON/arrays.
                        expr = (
                            compiler.text(Object, prop.id)
                            if metric.operator == "count"
                            else compiler.value(Object, final_type, prop)
                        )
                    aggregate: Expression
                    if metric.operator == "count":
                        aggregate = func.count(expr) if expr is not None else func.count()
                        kind = "integer"
                    else:
                        if metric.operator == "sum":
                            aggregate = func.sum(expr)
                        elif metric.operator == "avg":
                            aggregate = func.avg(expr)
                        elif metric.operator == "min":
                            aggregate = func.min(expr)
                        else:
                            aggregate = func.max(expr)
                        if metric.operator == "avg" and kind == "integer":
                            kind = "decimal"
                    expressions.append(aggregate.label(f"metric_{i}"))
                    result_types.append(kind)
                statement = select(
                    *([group.label("group_key")] if group is not None else []), *expressions
                ).where(Object.object_id.in_(ids), compiler.scope(Object, final_type))
                if group is not None:
                    statement = (
                        statement.group_by(group)
                        .order_by(group.asc().nulls_last())
                        .limit(request.max_groups + 1)
                    )
                rows = session.execute(statement).all()
                if len(rows) > request.max_groups:
                    raise ApplicationError(
                        "aggregation_too_large",
                        "Grouping cardinality exceeds the requested bound",
                        422,
                    )
                groups = []
                for row in rows:
                    data = row._mapping
                    values = {}
                    for i, metric in enumerate(request.metrics):
                        value = data[f"metric_{i}"]
                        kind = result_types[i]
                        if value is not None and kind == "integer":
                            value = int(value)
                        values[metric.name] = AggregateValue(data_type=kind, value=serial(value))
                    key = (
                        AggregateValue(data_type=group_type, value=serial(data["group_key"]))
                        if group is not None
                        else None
                    )
                    groups.append(AggregateGroup(key=key, values=values))
                return AggregateResult(
                    object_type=final_type, schema_version=schema.version, groups=groups
                )
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", "") in {"57014", "55P03"}:
                raise ApplicationError(
                    "query_timeout", "Aggregate exceeded the database time budget", 503
                ) from exc
            raise ApplicationError(
                "query_execution_failed",
                "Aggregate could not be executed within database limits",
                422,
            ) from exc

    def export_edges(
        self,
        principal: Principal,
        ontology_id: str,
        link_ids: tuple[str, ...],
        selected: dict[str, list[str]],
    ) -> list[tuple[str, str, str, str, str, str]]:
        """Authorized forward edges with BOTH endpoints in a caller's bounded query result."""
        from ontology_platform.db.models import Link
        from ontology_platform.objects.relationships import link_type

        with self.operation(principal, "link:read", f"{ontology_id}/links") as session:
            schema = active_definition(session, self.ontology(session, principal, ontology_id))
            compiler = QueryCompiler(schema, principal, self.authorizer)
            result = []
            for key in sorted(set(link_ids)):
                typed = link_type(schema, key)
                self.authorizer.require(
                    principal, "link:read", f"{principal.tenant_id}/{ontology_id}/links/{key}"
                )
                source_ids = selected.get(typed.source_type, [])
                target_ids = selected.get(typed.target_type, [])
                if not source_ids or not target_ids:
                    continue
                # The query result has already applied SQL row grants. Recheck grants here too.
                source = select(Object.object_id).where(
                    compiler.authorized(Object, typed.source_type)
                )
                target = select(Object.object_id).where(
                    compiler.authorized(Object, typed.target_type)
                )
                rows = session.scalars(
                    select(Link)
                    .where(
                        Link.tenant_id == principal.tenant_id,
                        Link.ontology_id == ontology_id,
                        Link.schema_version == schema.version,
                        Link.link_type_id == key,
                        Link.source_object_id.in_(source_ids),
                        Link.target_object_id.in_(target_ids),
                        Link.source_object_id.in_(source),
                        Link.target_object_id.in_(target),
                    )
                    .order_by(Link.source_object_id, Link.target_object_id)
                    .limit(5001)
                )
                for row in rows:
                    result.append(
                        (
                            key,
                            typed.source_type,
                            row.source_object_id,
                            typed.target_type,
                            row.target_object_id,
                            row.created_at.isoformat(),
                        )
                    )
                    if len(result) > 5000:
                        raise ApplicationError(
                            "semantic_resource_limit", "Export exceeds 5000 edges", 422
                        )
            return result
