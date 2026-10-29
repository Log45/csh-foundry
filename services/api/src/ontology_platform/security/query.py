"""SQL-expressible query grants; no Python post-filtering of result sets."""

from typing import Protocol, runtime_checkable

from pydantic import Field

from ontology_platform.queries.ast import Filter, Name, QueryModel, complexity
from ontology_platform.security.interfaces import Principal


class QueryGrant(QueryModel):
    # None means all schema-defined properties / all identities, never another tenant.
    visible_properties: tuple[Name, ...] | None = None
    allowed_object_ids: tuple[str, ...] | None = Field(default=None, max_length=1000)
    filter: Filter | None = None
    revision: str = Field(min_length=1, max_length=200)

    def check_complexity(self) -> None:
        complexity(self.filter)


@runtime_checkable
class QueryAuthorizer(Protocol):
    def query_grant(
        self, principal: Principal, ontology_id: str, object_type: str
    ) -> QueryGrant: ...
