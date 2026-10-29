"""Immutable internal composition; execution always uses QueryService's same AST/compiler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ontology_platform.queries.ast import (
    AggregateRequest,
    AggregateResult,
    Filter,
    Metric,
    QueryPage,
    QueryRequest,
)
from ontology_platform.queries.service import QueryService
from ontology_platform.security.interfaces import Principal


@dataclass(frozen=True)
class ObjectSet:
    service: QueryService
    principal: Principal
    ontology_id: str
    request: QueryRequest

    @classmethod
    def objects(
        cls, service: QueryService, principal: Principal, ontology_id: str, object_type: str
    ) -> ObjectSet:
        return cls(service, principal, ontology_id, QueryRequest(object_type=object_type))

    def _with(self, **changes: Any) -> ObjectSet:
        data = self.request.model_dump(mode="json", by_alias=True) | changes
        return ObjectSet(
            self.service, self.principal, self.ontology_id, QueryRequest.model_validate(data)
        )

    def where(self, condition: Filter) -> ObjectSet:
        other = condition.model_dump(mode="json", by_alias=True)
        if self.request.traverse:
            steps = [step.model_dump(mode="json", by_alias=True) for step in self.request.traverse]
            previous = steps[-1].get("filter")
            steps[-1]["filter"] = {"and": [previous, other]} if previous else other
            return self._with(traverse=steps, cursor=None, offset=0)
        combined = (
            {"and": [self.request.filter.model_dump(mode="json", by_alias=True), other]}
            if self.request.filter
            else other
        )
        return self._with(filter=combined, cursor=None, offset=0)

    def filter(self, **criteria: Any) -> ObjectSet:
        result = self
        for name, value in criteria.items():
            prop, separator, operator = name.rpartition("__")
            condition = {
                "property": prop if separator else name,
                "operator": operator if separator else "eq",
                "value": value,
            }
            parsed = QueryRequest.model_validate(
                {"object_type": self.request.object_type, "filter": condition}
            )
            assert parsed.filter is not None
            result = result.where(parsed.filter)
        return result

    def order_by(self, property: str, *, descending: bool = False) -> ObjectSet:
        if type(descending) is not bool:
            raise TypeError("descending must be a boolean")
        order = [s.model_dump() for s in self.request.order_by]
        return self._with(
            order_by=order + [{"property": property, "direction": "desc" if descending else "asc"}],
            cursor=None,
            offset=0,
        )

    def limit(self, count: int) -> ObjectSet:
        return self._with(limit=count, cursor=None)

    def select(self, *properties: str) -> ObjectSet:
        return self._with(select=list(properties), cursor=None)

    def after(self, cursor: str) -> ObjectSet:
        return self._with(cursor=cursor, offset=0, pagination="cursor")

    def offset(self, count: int) -> ObjectSet:
        return self._with(offset=count, cursor=None, pagination="offset")

    def traverse(self, link: str, *, inverse: bool = False) -> ObjectSet:
        if type(inverse) is not bool:
            raise TypeError("inverse must be a boolean")
        return self._with(
            traverse=[s.model_dump(mode="json", by_alias=True) for s in self.request.traverse]
            + [{"link": link, "direction": "inverse" if inverse else "forward"}],
            cursor=None,
            offset=0,
            order_by=[],
            select=None,
        )

    def where_results(self, condition: Filter) -> ObjectSet:
        return self._with(
            result_filter=condition.model_dump(mode="json", by_alias=True), cursor=None
        )

    def execute(self) -> QueryPage:
        return self.service.query(self.principal, self.ontology_id, self.request)

    def aggregate(self, *metrics: Metric, group_by: str | None = None) -> AggregateResult:
        data = self.request.model_dump(
            mode="json",
            by_alias=True,
            exclude={"order_by", "select", "limit", "offset", "cursor", "pagination"},
        )
        request = AggregateRequest.model_validate(
            data | {"metrics": [m.model_dump() for m in metrics], "group_by": group_by}
        )
        return self.service.aggregate(self.principal, self.ontology_id, request)
