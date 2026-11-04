"""Real controller loss and commit-boundary cancellation/revocation."""

from contextlib import contextmanager
from datetime import timedelta

from ontology_platform.db.models import ExecutionJob, MaterializationRecord
from ontology_platform.db.session import clock
from ontology_platform.execution.worker import ExecutionWorker
from ontology_platform.mappings.service import MappingService
from ontology_platform.projects.contracts import MemberChange
from sqlalchemy import func, select
from test_artifacts import store  # noqa: F401
from test_mappings import setup_mapping
from test_phase1 import database, historical_database, world  # noqa: F401
from test_security_platform import security  # noqa: F401


def content():
    return ("id,name\n" + "".join(f"F{i},Factory {i}\n" for i in range(3, 243))).encode()


def boundary(svc, run, callback, monkeypatch):
    original = MappingService.scope
    armed = True

    @contextmanager
    def scope(self, *args, **kwargs):
        nonlocal armed
        with original(self, *args, **kwargs) as session:
            yield session
        if armed:
            with svc.sessions() as session:
                row = session.get(ExecutionJob, (svc_actor.tenant_id, run.id))
                ready = row is not None and row.metrics.get("created") == 100
            if ready:
                armed = False
                callback()

    # Explicit caller supplies tenant via the run's persisted principal, not test globals.
    from ontology_platform.security.interfaces import Principal

    with svc.sessions() as session:
        row = session.scalar(select(ExecutionJob).where(ExecutionJob.id == run.id))
        svc_actor = Principal.model_validate(row.principal)
    monkeypatch.setattr(MappingService, "scope", scope)


def test_running_cancellation_preserves_committed_provenance(world, store, monkeypatch):  # noqa: F811
    svc, resource, spec, body = setup_mapping(world, store, content())
    run = svc.start(world.actor, resource.id, body)
    boundary(svc, run, lambda: svc.change(world.actor, run.id), monkeypatch)
    ExecutionWorker(svc).run_one()
    status = svc.status(world.actor, run.id)
    assert status.state == "CANCELLED" and status.metrics["created"] == 100, status
    assert world.objects.count(world.actor, spec.ontology_id, "Factory") == 100
    assert len(svc.provenance(world.actor, run.id, 100)) == 100
    resumed = svc.start(world.actor, resource.id, body)
    ExecutionWorker(svc).run_one()
    assert svc.status(world.actor, resumed.id).state == "SUCCEEDED"
    assert world.objects.count(world.actor, spec.ontology_id, "Factory") == 240


def test_revocation_between_committed_batches_prevents_more_writes(security, store, monkeypatch):  # noqa: F811
    from test_projects import grant_projects

    w, auth, admin, owner, other, _ = security
    grant_projects(admin, owner, other)
    svc, resource, spec, body = setup_mapping(
        w, store, content(), prepared=True, actor=owner, auth=auth
    )
    current = svc.get_project(owner, resource.project_id)
    current = svc.member(
        owner,
        resource.project_id,
        MemberChange(
            principal_id=other.principal_id, role="owner", expected_revision=current.revision
        ),
    )
    run = svc.start(owner, resource.id, body)
    boundary(
        svc,
        run,
        lambda: svc.member(
            owner,
            resource.project_id,
            MemberChange(
                principal_id=owner.principal_id, role="viewer", expected_revision=current.revision
            ),
        ),
        monkeypatch,
    )
    ExecutionWorker(svc).run_one()
    status = svc.status(owner, run.id)
    assert status.state == "FAILED" and status.metrics["created"] == 100, status
    assert len(svc.provenance(owner, run.id, 100)) == 100


def crash_after_checkpoint(url, schema, settings, storage, tenant, run, pipe):
    import os

    from ontology_platform.artifacts.s3 import S3ArtifactStore
    from ontology_platform.security.local import LocalAuthorizer
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(url, connect_args={"options": "-c search_path=" + schema})
    svc = MappingService(
        sessionmaker(engine, expire_on_commit=False),
        LocalAuthorizer(settings),
        storage,
        S3ArtifactStore(storage),
    )
    original = MappingService.scope

    @contextmanager
    def scope(self, *args, **kwargs):
        with original(self, *args, **kwargs) as session:
            yield session
        with svc.sessions() as session:
            row = session.get(ExecutionJob, (tenant, run))
            if row is not None and row.metrics.get("created") == 100:
                pipe.send(True)
                pipe.close()
                os._exit(91)

    MappingService.scope = scope
    ExecutionWorker(svc).run_one()


def test_real_controller_exit_after_batch_recovers_pinned_run(world, store):  # noqa: F811
    import multiprocessing

    from sqlalchemy import text

    svc, resource, spec, body = setup_mapping(world, store, content())
    run = svc.start(world.actor, resource.id, body)
    with world.sessions() as session:
        schema = session.scalar(text("SELECT current_schema()"))
    receive, send = multiprocessing.get_context("spawn").Pipe(duplex=False)
    process = multiprocessing.get_context("spawn").Process(
        target=crash_after_checkpoint,
        args=(
            world.settings.database_url.get_secret_value(),
            schema,
            world.settings,
            svc.settings,
            world.actor.tenant_id,
            run.id,
            send,
        ),
    )
    process.start()
    try:
        assert receive.poll(60), "Controller never reached durable checkpoint"
        assert receive.recv()
        process.join(10)
        assert process.exitcode == 91
    finally:
        if process.is_alive():
            process.kill()
            process.join()
        receive.close()
        send.close()
    with world.sessions.begin() as session:
        row = session.get(ExecutionJob, (world.actor.tenant_id, run.id))
        row.lease_until = clock(session) - timedelta(seconds=1)
        assert (
            session.scalar(
                select(func.count())
                .select_from(MaterializationRecord)
                .where(MaterializationRecord.run_id == run.id)
            )
            == 100
        )
    ExecutionWorker(svc).run_one()
    status = svc.status(world.actor, run.id)
    assert (
        status.state == "SUCCEEDED" and status.attempts == 2 and status.metrics["created"] == 240
    ), status
    assert world.objects.count(world.actor, spec.ontology_id, "Factory") == 240
