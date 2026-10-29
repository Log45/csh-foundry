"""Schema-resolved SQLAlchemy compilation. All client values/JSON keys are bound."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from ontology_schema.models import OntologyDefinition, PropertyDefinition
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Numeric,
    Text,
    and_,
    case,
    false,
    func,
    literal,
    not_,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import aliased
from sqlalchemy.orm.util import AliasedClass
from sqlalchemy.sql import ColumnElement, Select
from sqlalchemy.types import TypeEngine

from ontology_platform.db.models import Link, Object
from ontology_platform.errors import ApplicationError
from ontology_platform.objects.validation import object_type
from ontology_platform.queries.ast import (
    All,
    Filter,
    Negation,
    ObjectSetRequest,
    Predicate,
    Sort,
    TraversalStep,
)
from ontology_platform.security.interfaces import Authorizer, Principal
from ontology_platform.security.query import PolicyAudit, QueryAuthorizer, QueryGrant

Entity = type[Object] | AliasedClass[Object]
Expression = ColumnElement[Any]
NUMERIC = {"integer", "float", "decimal"}
ORDERABLE = NUMERIC | {"date", "timestamp"}
SORTABLE = ORDERABLE | {"string", "uuid", "boolean"}


def invalid(message: str) -> ApplicationError:
    return ApplicationError("invalid_query", message, 422)


class QueryCompiler:
    def __init__(self, schema: OntologyDefinition, principal: Principal, authorizer: Authorizer):
        self.schema = schema
        self.principal = principal
        self.authorizer = authorizer
        self.grants: dict[str, QueryGrant] = {}

    def grant(self, type_id: str) -> QueryGrant:
        if type_id not in self.grants:
            if not isinstance(self.authorizer, QueryAuthorizer):
                raise ApplicationError(
                    "query_policy_required", "SQL query authorization is required", 403
                )
            self.authorizer.require(
                self.principal,
                "object:query",
                f"{self.principal.tenant_id}/{self.schema.id}/objects/{type_id}",
            )
            grant = self.authorizer.query_grant(self.principal, self.schema.id, type_id)
            if not isinstance(grant, QueryGrant):
                raise ApplicationError(
                    "invalid_query_policy", "Invalid query authorization grant", 503
                )
            grant = grant.model_copy(deep=True)
            try:
                grant.check_complexity()
            except ValueError as exc:
                raise ApplicationError(
                    "invalid_query_policy", "Query policy exceeds limits", 503
                ) from exc
            typed = object_type(self.schema, type_id)
            if grant.visible_properties is not None and set(grant.visible_properties) - {
                p.id for p in typed.properties
            }:
                raise ApplicationError(
                    "invalid_query_policy", "Query policy references unknown properties", 503
                )
            self.grants[type_id] = grant
        return self.grants[type_id]

    def prop(self, type_id: str, name: str, *, trusted: bool = False) -> PropertyDefinition:
        typed = object_type(self.schema, type_id)
        result = next((p for p in typed.properties if p.id == name), None)
        if result is None:
            raise invalid(f"Unknown property: {name}")
        visible = self.grant(type_id).visible_properties
        if not trusted and visible is not None and name not in visible:
            if isinstance(self.authorizer, PolicyAudit):
                self.authorizer.policy_denial(
                    self.principal,
                    "property:read",
                    f"{self.principal.tenant_id}/{self.schema.id}/objects/{type_id}/properties/{name}",
                )
            raise ApplicationError("property_forbidden", "Property is not query-visible", 403)
        return result

    def scope(self, entity: Entity, type_id: str) -> Expression:
        return and_(
            entity.tenant_id == self.principal.tenant_id,
            entity.ontology_id == self.schema.id,
            entity.object_type_id == type_id,
            entity.schema_version == self.schema.version,
        )

    @staticmethod
    def text(entity: Entity, name: str) -> Expression:
        return cast(Expression, entity.properties.op("->>", return_type=Text())(name))

    def value(self, entity: Entity, type_id: str, prop: PropertyDefinition) -> Expression:
        if prop.array or prop.data_type == "json":
            return cast(Expression, entity.properties[prop.id])
        raw = self.text(entity, prop.id)
        if prop.data_type == "string":
            return raw.collate("C")
        kinds: dict[str, TypeEngine[Any]] = {
            "integer": BigInteger(),
            "float": Float(),
            "decimal": Numeric(),
            "date": Date(),
            "timestamp": DateTime(timezone=True),
            "uuid": PGUUID(as_uuid=False),
            "boolean": Boolean(),
        }
        # PostgreSQL may reorder WHERE predicates. CASE prevents casts on other
        # tenants/types/schemas sharing the same JSON key with another datatype.
        return case((self.scope(entity, type_id), raw.cast(kinds[prop.data_type])), else_=None)

    def leaf(self, entity: Entity, type_id: str, node: Predicate, *, trusted: bool) -> Expression:
        prop = self.prop(type_id, node.property, trusted=trusted)
        raw_text = self.text(entity, prop.id)
        if node.operator == "is_null":
            return raw_text.is_(None)  # Missing and explicit JSON null are both null for queries.
        if node.operator == "is_not_null":
            return raw_text.is_not(None)
        if node.operator in {"gt", "gte", "lt", "lte"} and (
            prop.array or prop.data_type not in ORDERABLE
        ):
            raise invalid("Ordering comparisons require numeric/date/timestamp scalar properties")
        strings = node.operator in {"contains", "starts_with", "ends_with"}
        if strings:
            if prop.array or prop.data_type != "string" or not isinstance(node.value, str):
                raise invalid("String operators require a scalar string property and operand")
        else:
            try:
                prop.model_copy(update={"enum": ()}).validate_value(node.value)
            except ValueError as exc:
                raise invalid(f"Invalid operand type/representation for {prop.id}") from exc
        expression = self.value(entity, type_id, prop)
        value: Any = node.value
        if not prop.array:
            if prop.data_type == "decimal":
                value = Decimal(str(value))
            elif prop.data_type == "date":
                value = date.fromisoformat(str(value))
            elif prop.data_type == "timestamp":
                value = datetime.fromisoformat(str(value))
        predicate: Expression
        if strings:
            # Literal substring matching; % and _ are not client SQL wildcards.
            pattern = str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            if node.operator in {"contains", "ends_with"}:
                pattern = "%" + pattern
            if node.operator in {"contains", "starts_with"}:
                pattern += "%"
            predicate = expression.like(pattern, escape="\\")
        else:
            bound = (
                literal(value, type_=JSONB)
                if prop.array or prop.data_type == "json"
                else literal(value, type_=expression.type)
            )
            operations = {
                "eq": expression == bound,
                "ne": expression != bound,
                "gt": expression > bound,
                "gte": expression >= bound,
                "lt": expression < bound,
                "lte": expression <= bound,
            }
            predicate = operations[node.operator]
        # Two-valued leaves: even ne is false for missing/null. NOT then complements
        # the complete object set, including nulls, without SQL UNKNOWN surprises.
        if (
            prop.id == "operationalStatus"
            and not prop.array
            and prop.data_type == "string"
            and node.operator == "eq"
        ):
            # A fixed-width expression lookup can index arbitrary future string lengths.
            # Exact comparison above always rechecks hash matches, so collisions cannot add rows.
            predicate = and_(
                predicate,
                func.md5(raw_text) == func.md5(literal(node.value, type_=Text())),
                func.md5(entity.ontology_id) == func.md5(literal(self.schema.id, type_=Text())),
                func.md5(entity.object_type_id) == func.md5(literal(type_id, type_=Text())),
            )
        return and_(raw_text.is_not(None), predicate)

    def predicate(
        self, entity: Entity, type_id: str, node: Filter | None, *, trusted: bool = False
    ) -> Expression:
        if node is None:
            return literal(True)
        if isinstance(node, Predicate):
            return self.leaf(entity, type_id, node, trusted=trusted)
        if isinstance(node, Negation):
            return not_(self.predicate(entity, type_id, node.condition, trusted=trusted))
        parts = [self.predicate(entity, type_id, c, trusted=trusted) for c in node.conditions]
        return and_(*parts) if isinstance(node, All) else or_(*parts)

    def authorized(self, entity: Entity, type_id: str) -> Expression:
        grant = self.grant(type_id)
        try:
            policy = self.predicate(entity, type_id, grant.filter, trusted=True)
        except ApplicationError as exc:
            raise ApplicationError(
                "invalid_query_policy", "Query policy cannot be compiled", 503
            ) from exc
        parts = [self.scope(entity, type_id), policy]
        if grant.allowed_object_ids is not None:
            parts.append(entity.object_id.in_(grant.allowed_object_ids))
        return and_(*parts)

    def step(self, source: str, step: TraversalStep) -> tuple[str, str, bool]:
        matches = [
            t for t in self.schema.link_types if t.id == step.link or t.inverse_name == step.link
        ]
        if len(matches) != 1:
            raise invalid("Unknown or ambiguous link type")
        link = matches[0]
        inverse = step.direction == "inverse" or link.inverse_name == step.link
        if source != (link.target_type if inverse else link.source_type):
            raise invalid("Traversal source type does not match the link definition")
        self.authorizer.require(
            self.principal,
            "link:read",
            f"{self.principal.tenant_id}/{self.schema.id}/links/{link.id}",
        )
        return link.id, link.source_type if inverse else link.target_type, inverse

    def object_set(self, request: ObjectSetRequest) -> tuple[str, Select[Any]]:
        source_type = request.object_type
        object_type(self.schema, source_type)
        if not request.traverse:
            return source_type, select(Object.object_id).where(
                self.authorized(Object, source_type),
                self.predicate(Object, source_type, request.filter),
                self.predicate(Object, source_type, request.result_filter),
            )
        root = aliased(Object, name="q_root")
        ids = select(root.object_id).where(
            self.authorized(root, source_type), self.predicate(root, source_type, request.filter)
        )
        for i, step in enumerate(request.traverse):
            # Optimization fences prevent exponential join-order search when paths grow.
            previous = ids.cte(f"q_path_{i}").prefix_with("MATERIALIZED", dialect="postgresql")
            link_id, target_type, inverse = self.step(source_type, step)
            target = aliased(Object, name=f"q_target_{i}")
            edge = aliased(Link, name=f"q_edge_{i}")
            start_type = edge.target_object_type_id if inverse else edge.source_object_type_id
            start_id = edge.target_object_id if inverse else edge.source_object_id
            end_type = edge.source_object_type_id if inverse else edge.target_object_type_id
            end_id = edge.source_object_id if inverse else edge.target_object_id
            ids = (
                select(target.object_id)
                .join(
                    edge,
                    and_(
                        edge.tenant_id == target.tenant_id,
                        edge.ontology_id == target.ontology_id,
                        end_type == target.object_type_id,
                        end_id == target.object_id,
                    ),
                )
                .where(
                    self.authorized(target, target_type),
                    self.predicate(target, target_type, step.filter),
                    edge.tenant_id == self.principal.tenant_id,
                    edge.ontology_id == self.schema.id,
                    edge.schema_version == self.schema.version,
                    edge.link_type_id == link_id,
                    start_type == source_type,
                    start_id.in_(select(previous.c.object_id)),
                )
                .distinct()
            )
            source_type = target_type
        final_ids = ids.cte("q_path_final").prefix_with("MATERIALIZED", dialect="postgresql")
        # The final outer object query carries its own independent scope restrictions.
        final = select(Object.object_id).where(
            self.authorized(Object, source_type),
            Object.object_id.in_(select(final_ids.c.object_id)),
            self.predicate(Object, source_type, request.result_filter),
        )
        return source_type, final

    def sorting(self, type_id: str, order: tuple[Sort, ...]) -> list[tuple[Expression, bool]]:
        result = []
        for sort in order:
            prop = self.prop(type_id, sort.property)
            if prop.array or prop.data_type not in SORTABLE:
                raise invalid("Property is not sortable")
            result.append((self.value(Object, type_id, prop), sort.direction == "desc"))
        result.append((Object.object_id.collate("C"), False))
        return result


def seek_after(sorts: list[tuple[Expression, bool]], values: list[Any]) -> Expression:
    prefixes: list[Expression] = []
    choices = []
    for (expression, descending), value in zip(sorts, values, strict=True):
        if value is not None:
            bound = literal(value, type_=expression.type)
            after = expression < bound if descending else expression > bound
            choices.append(and_(*prefixes, or_(after, expression.is_(None))))
            prefixes.append(expression == bound)
        else:
            prefixes.append(expression.is_(None))
    return or_(*choices) if choices else false()
