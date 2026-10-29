import json
from pathlib import Path

import pytest
from ontology_platform.db.models import Object
from ontology_platform.errors import ApplicationError
from ontology_platform.queries.ast import AggregateRequest, QueryRequest
from ontology_platform.queries.compiler import QueryCompiler
from ontology_platform.queries.cursor import CursorCodec
from ontology_platform.security.interfaces import Principal
from ontology_platform.security.query import QueryGrant
from ontology_schema.models import OntologyDefinition
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql


@pytest.mark.parametrize(
    "payload",
    [
        {"limit": 0},
        {"limit": 201},
        {"limit": None},
        {"limit": True},
        {"offset": 10001},
        {"offset": 1, "cursor": "token"},
        {"filter": {"and": []}},
        {"filter": {"or": []}},
        {"filter": {"not": []}},
        {"filter": {"property": "x", "operator": "execute", "value": "code"}},
        {"filter": {"property": "x", "operator": "eq", "value": None}},
        {"filter": {"property": "x", "operator": "is_null", "value": 1}},
        {"filter": {"property": "x", "operator": "eq", "value": float("nan")}},
        {"filter": {"property": "x", "operator": "eq", "value": "x" * 8193}},
        {"order_by": [{"property": "x", "direction": "up"}]},
        {"order_by": [{"property": "x"}] * 2},
        {"order_by": [{"property": str(i)} for i in range(5)]},
        {"select": [str(i) for i in range(33)]},
        {"select": ["x", "x"]},
        {"traverse": [{"link": "x"}] * 5},
        {"filter": {"and": [{"property": "x", "operator": "eq", "value": 1}] * 65}},
    ],
)
def test_ast_rejects_invalid_and_unbounded_queries(payload):
    with pytest.raises(ValidationError):
        QueryRequest.model_validate({"object_type": "Machine"} | payload)


def test_nesting_and_total_predicate_limits():
    node = {"property": "x", "operator": "eq", "value": 1}
    for _ in range(8):
        node = {"not": node}
    with pytest.raises(ValidationError):
        QueryRequest.model_validate({"object_type": "Machine", "filter": node})
    leaves = [{"property": "x", "operator": "eq", "value": 1}] * 33
    with pytest.raises(ValidationError):
        QueryRequest.model_validate(
            {"object_type": "Machine", "filter": {"and": leaves}, "result_filter": {"or": leaves}}
        )
    with pytest.raises(ValidationError):
        AggregateRequest(
            object_type="Machine", metrics=[{"name": str(i), "operator": "count"} for i in range(9)]
        )
    with pytest.raises(ValidationError):
        AggregateRequest(object_type="Machine", metrics=[{"name": "x", "operator": "sum"}])


class Policy:
    def require(self, principal, operation, resource):
        return None

    def query_grant(self, principal, ontology_id, object_type):
        return QueryGrant(revision="sql-test")


def test_compiler_binds_values_keys_and_all_scopes():
    data = json.loads(
        (Path(__file__).resolve().parents[3] / "ontologies/examples/manufacturing.json").read_text()
    )
    schema = OntologyDefinition.model_validate(data)
    actor = Principal(tenant_id=schema.tenant_id, principal_id="sql-test")
    compiler = QueryCompiler(schema, actor, Policy())
    injection = "' OR 1=1; DROP TABLE objects; --"
    request = QueryRequest.model_validate(
        {
            "object_type": "Machine",
            "filter": {"property": "machineName", "operator": "eq", "value": injection},
        }
    )
    kind, ids = compiler.object_set(request)
    statement = select(Object.object_id).where(
        compiler.scope(Object, kind), Object.object_id.in_(ids)
    )
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert injection not in sql and injection in compiled.params.values()
    assert "Machine" not in sql and "Machine" in compiled.params.values()
    assert actor.tenant_id in compiled.params.values()
    assert "machineName" not in sql and "machineName" in compiled.params.values()
    assert (
        "tenant_id" in sql
        and "ontology_id" in sql
        and "object_type_id" in sql
        and "schema_version" in sql
    )


def test_cursor_signature_expiration_and_no_sort_values():
    codec = CursorCodec(b"a" * 32)
    token = codec.encode({"anchor": "MCH-001", "values_hash": "digest"})
    assert codec.decode(token)["anchor"] == "MCH-001"
    with pytest.raises(ApplicationError):
        CursorCodec(b"b" * 32).decode(token)
    with pytest.raises(ApplicationError):
        codec.decode(token[:-8] + "deadbeef")


def test_cursor_expiration_and_restart_key_rotation():
    from unittest.mock import patch

    codec = CursorCodec()
    with patch("ontology_platform.queries.cursor.time.time", return_value=0):
        expired = codec.encode({"anchor": "x"})
    with pytest.raises(ApplicationError) as caught:
        codec.decode(expired)
    assert caught.value.code == "invalid_cursor"


def test_oversized_cursor_identity_and_incompatible_page_modes():
    with pytest.raises(ApplicationError) as caught:
        CursorCodec().encode({"anchor": "x" * 20000})
    assert caught.value.code == "cursor_too_large"
    with pytest.raises(ValidationError):
        QueryRequest(object_type="Machine", pagination="offset", cursor="token")
