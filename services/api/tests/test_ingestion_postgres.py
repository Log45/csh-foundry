"""Real PostgreSQL source reads under a generated, SELECT-only role."""

from uuid import uuid4

import pytest
from ontology_platform.errors import ApplicationError
from ontology_platform.ingestion.catalog import Binding, InputColumn
from ontology_platform.ingestion.connectors import extract
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from test_ingestion import (
    MappingInput,
    MappingRef,
    PropertyMapping,
    RunInput,
    SourceInput,
    finish,
)
from test_ingestion import database as database
from test_ingestion import ingestion as ingestion

pytestmark = pytest.mark.integration


@pytest.fixture
def registered_postgres(ingestion):
    world, service, worker = ingestion
    role = "source_reader_" + uuid4().hex
    password = uuid4().hex
    with world.engine.begin() as connection:
        schema = connection.scalar(text("SELECT current_schema()"))
        # Identifiers/password are generated hex, never request input. The role is dropped below.
        connection.exec_driver_sql(
            f"CREATE ROLE {role} LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB NOCREATEROLE"
        )
        connection.exec_driver_sql(
            'CREATE TABLE pg_factory_source ("factoryId" text PRIMARY KEY,'
            '"factoryName" text NOT NULL,location text NOT NULL)'
        )
        connection.exec_driver_sql(
            "INSERT INTO pg_factory_source VALUES ('FAC-PG-1','PG One','Local'),"
            "('FAC-PG-2','PG Two','Local')"
        )
        connection.exec_driver_sql(f'GRANT USAGE ON SCHEMA "{schema}" TO {role}')
        connection.exec_driver_sql(f"GRANT SELECT ON pg_factory_source TO {role}")
    try:
        url = make_url(world.settings.database_url.get_secret_value()).set(
            username=role, password=password
        )
        binding = Binding(
            tenant_id=world.actor.tenant_id,
            key="postgres",
            kind="postgres",
            url=SecretStr(url.render_as_string(hide_password=False)),
            table_schema=schema,
            table="pg_factory_source",
            source_key_column="factoryId",
            columns=[InputColumn(name=n) for n in ["factoryId", "factoryName", "location"]],
        )
        yield world, service, worker, binding, role, password
    finally:
        with world.engine.begin() as connection:
            connection.exec_driver_sql(f"DROP OWNED BY {role}")
            connection.exec_driver_sql(f"DROP ROLE {role}")


def test_postgres_connector_and_governed_ingestion(registered_postgres, ingestion):
    world, service, worker, binding, role, password = registered_postgres
    first = extract(binding, 0, 1)
    second = extract(binding, 1, 1)
    assert len(first.rows) == len(second.rows) == 1 and first.fingerprint == second.fingerprint
    assert not first.eof and second.eof
    worker.catalog.bindings[(world.actor.tenant_id, "postgres")] = binding
    source = service.create_source(
        world.actor,
        world.definition.id,
        SourceInput(
            id="Postgres", name="Read only", binding="postgres", identity_namespace="pg-factories"
        ),
    )
    assert password not in source.model_dump_json() and role not in source.model_dump_json()
    service.create_mapping(
        world.actor,
        world.definition.id,
        MappingInput(
            id="Postgres",
            source_id="Postgres",
            source_version=1,
            schema_version=world.definition.version,
            object_type="Factory",
            identity_column="factoryId",
            properties=[
                PropertyMapping(property=n, column=n)
                for n in ["factoryId", "factoryName", "location"]
            ],
        ),
    )
    run = service.submit(
        world.actor,
        world.definition.id,
        RunInput(idempotency_key="postgres", mappings=[MappingRef(id="Postgres", version=1)]),
    )
    result = finish(ingestion, run)
    assert result.status == "COMPLETED" and result.created == 2


def test_postgres_predicates_are_parameterized(registered_postgres):
    *_, binding, role, password = registered_postgres
    filtered = binding.model_copy(update={"equals": {"factoryId": "x' OR 1=1 --"}})
    assert extract(filtered, 0, 10).rows == []
    filtered = binding.model_copy(update={"equals": {"factoryId": "FAC-PG-1"}})
    assert len(extract(filtered, 0, 10).rows) == 1
    with pytest.raises(ApplicationError):
        extract(binding.model_copy(update={"equals": {"not_allowlisted": "x"}}), 0, 10)


def test_postgres_rejects_write_credentials(registered_postgres):
    world, service, worker, binding, role, password = registered_postgres
    with pytest.raises(ApplicationError) as error:
        extract(binding.model_copy(update={"url": world.settings.database_url}), 0, 10)
    assert error.value.code == "source_credentials_not_readonly"


def test_postgres_source_statement_timeout(registered_postgres):
    world, service, worker, binding, role, password = registered_postgres
    with world.engine.begin() as connection:
        connection.exec_driver_sql("""CREATE VIEW pg_slow_source AS
            SELECT 'FAC-SLOW'::text AS "factoryId", 'Slow'::text AS "factoryName",
            'Local'::text AS location FROM pg_sleep(6)""")
        connection.exec_driver_sql(f"GRANT SELECT ON pg_slow_source TO {role}")
    with pytest.raises(ApplicationError) as error:
        extract(binding.model_copy(update={"table": "pg_slow_source"}), 0, 10)
    assert error.value.code == "source_read_error" and error.value.status_code == 503
