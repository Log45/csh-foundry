"""Durable recovery, including actual subprocess termination, on PostgreSQL."""

import json
import os
import select as io_select
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from ontology_platform.db.models import (
    IngestionMapping,
    IngestionRun,
    IngestionSource,
    IngestionStage,
    Object,
)
from ontology_platform.errors import ApplicationError
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from test_ingestion import count, finish, submit
from test_ingestion import database as database
from test_ingestion import ingestion as ingestion
from test_phase1 import migrate

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("when", ["before_commit", "before_checkpoint", "after_commit"])
def test_real_worker_process_crash(ingestion, when):
    world, service, worker = ingestion
    run = submit(ingestion, mappings=["Factory"], policy="quarantine", size=2)
    with world.engine.connect() as connection:
        schema = connection.scalar(text("SELECT current_schema()"))
    environment = dict(
        os.environ,
        TEST_DATABASE_URL=world.settings.database_url.get_secret_value(),
        CRASH_SCHEMA=schema,
        CRASH_TENANT=str(world.actor.tenant_id),
        CRASH_PRINCIPAL=world.actor.principal_id,
        CRASH_WHEN=when,
        CRASH_CATALOG=json.dumps(
            [b.model_dump(mode="json") for b in worker.catalog.bindings.values()]
        ),
    )
    code = """
import os,sys
from sqlalchemy import create_engine,event
from sqlalchemy.orm import sessionmaker
from ontology_platform.config import Settings
from ontology_platform.security.local import LocalAuthorizer
from ontology_platform.security.interfaces import Principal
from ontology_platform.ingestion.catalog import SourceCatalog
from ontology_platform.ingestion.worker import IngestionWorker
from pydantic import SecretStr
settings=Settings(database_url=SecretStr(os.environ["TEST_DATABASE_URL"]),trusted_local_identity=True,
    local_tenant_id=os.environ["CRASH_TENANT"],local_principal_id=os.environ["CRASH_PRINCIPAL"],_env_file=None)
engine=create_engine(os.environ["TEST_DATABASE_URL"],
    connect_args={"options":"-c search_path="+os.environ["CRASH_SCHEMA"]})
worker=IngestionWorker(sessionmaker(engine),LocalAuthorizer(settings),SourceCatalog.from_json(SecretStr(os.environ["CRASH_CATALOG"])))
p=Principal(tenant_id=settings.local_tenant_id,principal_id=settings.local_principal_id)
key,token=worker.claim(p,"manufacturing")
while worker.get(p,"manufacturing",key).phase!="OBJECTS":worker.step(p,"manufacturing",key,token)
def stop():
    print("READY",flush=True)
    sys.stdin.readline()
if os.environ["CRASH_WHEN"]=="before_checkpoint":
    def inserted(conn,cursor,statement,parameters,context,executemany):
        if statement.startswith("INSERT INTO objects"):stop()
    event.listen(engine,"after_cursor_execute",inserted)
    worker.step(p,"manufacturing",key,token)
elif os.environ["CRASH_WHEN"]=="before_commit":
    worker.step(p,"manufacturing",key,token,before_commit=stop)
else:
    worker.step(p,"manufacturing",key,token)
    print("COMMITTED",flush=True)
    os._exit(17)
"""
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", code],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        assert io_select.select([process.stdout], [], [], 30)[0], (
            "Worker failed to reach crash boundary"
        )
        line = process.stdout.readline().strip()
        assert line == ("COMMITTED" if when == "after_commit" else "READY"), line
        if when != "after_commit":
            process.kill()
        process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
    assert count(world, Object) == (2 if when == "after_commit" else 0)
    if when == "after_commit":
        assert process.returncode == 17
    assert worker.claim(world.actor, world.definition.id) is None
    with world.sessions.begin() as session:
        session.execute(
            update(IngestionRun)
            .where(IngestionRun.id == run.id)
            .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
        )
    result = finish(ingestion, run)
    assert result.status == "COMPLETED" and result.created == 6 and count(world, Object) == 6
    with world.sessions() as session:
        assert all(r.version == 1 for r in session.scalars(select(Object)))


def test_concurrent_workers_claim_distinct_jobs(ingestion):
    world, service, worker = ingestion
    first = submit(ingestion, mappings=["Factory"])
    second = submit(ingestion, mappings=["Factory"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker.run_one(world.actor, world.definition.id), [0, 1]))
    assert set(results) == {first.id, second.id}
    assert all(
        service.get(world.actor, world.definition.id, key).status == "COMPLETED" for key in results
    )
    assert count(world, Object) == 6


def test_retry_exhaustion_and_renewal(ingestion):
    world, service, worker = ingestion
    run = submit(ingestion, mappings=["Factory"])
    for _ in range(3):
        key, token = worker.claim(world.actor, world.definition.id)
        worker.renew(world.actor, world.definition.id, key, token)
        with world.sessions.begin() as session:
            session.execute(
                update(IngestionRun)
                .where(IngestionRun.id == key)
                .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
            )
        with pytest.raises(ApplicationError):
            worker.renew(world.actor, world.definition.id, key, token)
    assert worker.claim(world.actor, world.definition.id) is None
    result = service.get(world.actor, world.definition.id, run.id)
    assert (
        result.status == "FAILED"
        and result.last_error == "lease_exhausted"
        and result.attempts == 3
    )
    assert count(world, Object) == 0


def test_config_and_plan_immutable_and_request_uniqueness(ingestion):
    world, service, worker = ingestion
    run = submit(ingestion, key="key", mappings=["Factory"])
    assert submit(ingestion, key="key", mappings=["Factory"]).id == run.id
    with pytest.raises(ApplicationError):
        submit(ingestion, key="key", mappings=["Machine"])
    for model, values in [
        (IngestionSource, {"definition_json": "{}"}),
        (IngestionMapping, {"definition_json": "{}"}),
        (IngestionRun, {"principal_id": "spoofed"}),
    ]:
        with pytest.raises(IntegrityError), world.sessions.begin() as session:
            session.execute(update(model).values(**values))


def test_retention_purges_only_terminal_staging(ingestion):
    world, service, worker = ingestion
    run = finish(ingestion, submit(ingestion, mappings=["Factory"]))
    assert count(world, IngestionStage) == 6
    with world.sessions.begin() as session:
        session.execute(
            update(IngestionRun)
            .where(IngestionRun.id == run.id)
            .values(completed_at=datetime.now(UTC) - timedelta(days=8))
        )
    assert service.cleanup(world.actor, world.definition.id) == 1
    assert count(world, IngestionStage) == 0 and count(world, Object) == 6
    result = service.get(world.actor, world.definition.id, run.id)
    assert result.staging_purged_at and result.created == 6


def test_phase3_upgrade_and_downgrade_preserve_objects(ingestion):
    from test_phase1 import machine

    world, _, _ = ingestion
    world.objects.create(world.actor, world.definition.id, machine())
    migrate(world.engine, "0007_edit_provenance", downgrade=True)
    migrate(world.engine)
    assert world.objects.get(world.actor, world.definition.id, "Machine", "MCH-001").version == 1
