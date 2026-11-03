"""Phase 12 storage, lifecycle and security contracts, including real MinIO."""

import hashlib
import io
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber
from ontology_platform.artifacts.config import StorageSettings
from ontology_platform.artifacts.contracts import CreateArtifact, InitiateUpload
from ontology_platform.artifacts.s3 import S3ArtifactStore, translate
from ontology_platform.artifacts.service import ArtifactService
from ontology_platform.artifacts.storage import Failure, ObjectKey, StorageError
from ontology_platform.db.models import ArtifactVersion
from ontology_platform.errors import ApplicationError
from ontology_platform.projects.contracts import CreateProject, MemberChange, ShareChange
from pydantic import ValidationError
from sqlalchemy import delete, text, update
from sqlalchemy.exc import IntegrityError
from test_phase1 import client_for, database, historical_database, make_world, migrate, world  # noqa: F401
from test_projects import grant_projects, raises
from test_security_platform import security  # noqa: F401


@pytest.fixture
def store():
    if os.environ.get("FOUNDRY_ARTIFACT_BACKEND") != "s3":
        pytest.skip("NOT RUN: use scripts/validate_phase12.py for isolated real MinIO")
    return S3ArtifactStore(StorageSettings())


def service(w, store, auth=None):
    return ArtifactService(w.sessions, auth or w.registry.authorizer, store.settings, store)


def artifact(s, p):
    project = s.create_project(p, CreateProject(name="Files " + uuid4().hex))
    return s.create(p, project.id, CreateArtifact(name="Artifact"))


def initiate(s, p, key, data=b"hello"):
    return s.initiate(
        p,
        key,
        InitiateUpload(
            filename="file.bin", size=len(data), checksum=hashlib.sha256(data).hexdigest()
        ),
    )


def commit(s, p, key, data=b"hello"):
    v = initiate(s, p, key, data)
    s.upload(p, key, v.id, io.BytesIO(data), len(data), v.checksum)
    return s.finalize(p, key, v.id)


def test_real_storage_stream_integrity_missing_immutable_multipart(store):
    data = b"a" * (store.settings.part_bytes + 17)
    key = ObjectKey(uuid4(), uuid4(), uuid4())
    digest = hashlib.sha256(data).hexdigest()
    try:
        assert not store.exists(key)
        with pytest.raises(StorageError) as exc:
            store.verify(key, len(data), digest)
        assert exc.value.category == Failure.MISSING
        store.put(key, io.BytesIO(data), len(data), digest)
        assert store.head(key).size == len(data)
        chunks = list(store.chunks(key))
        assert max(map(len, chunks)) <= 65536
        assert b"".join(chunks) == data
        with pytest.raises(StorageError) as exc:
            store.put(key, io.BytesIO(data), len(data), digest)
        assert exc.value.category == Failure.EXISTS
        with pytest.raises(StorageError) as exc:
            store.verify(key, len(data), "0" * 64)
        assert exc.value.category == Failure.INTEGRITY
        with pytest.raises(StorageError):
            store.verify(key, 1, digest)
        # Incomplete multipart transfer aborts its exact session.
        broken = ObjectKey(key.tenant, key.artifact, uuid4())
        with pytest.raises(StorageError):
            store.put(broken, io.BytesIO(b"short"), len(data), digest)
        assert not store.exists(broken)
        response = store.client.list_multipart_uploads(
            Bucket=store.settings.bucket, Prefix=str(broken)
        )
        assert not response.get("Uploads")
    finally:
        store.delete(key)
    assert not store.exists(key)


def test_lifecycle_versions_recovery_concurrency_and_archive(world, store):  # noqa: F811
    s, p = service(world, store), world.actor
    a = artifact(s, p)
    pending = initiate(s, p, a.id)
    raises(503, lambda: s.finalize(p, a.id, pending.id))
    raises(409, lambda: s.upload(p, a.id, pending.id, io.BytesIO(b"bad"), 3, "0" * 64))
    key = ObjectKey(p.tenant_id, a.id, pending.id)
    store.client.create_multipart_upload(Bucket=store.settings.bucket, Key=str(key))
    s.upload(p, a.id, pending.id, io.BytesIO(b"hello"), 5, pending.checksum)
    assert not store.client.list_multipart_uploads(
        Bucket=store.settings.bucket, Prefix=str(key)
    ).get("Uploads")
    # Simulate API restart after byte write before metadata finalization.
    s = service(world, store)
    s.upload(p, a.id, pending.id, io.BytesIO(b"hello"), 5, pending.checksum)
    v = s.finalize(p, a.id, pending.id)
    assert s.finalize(p, a.id, v.id) == v
    raises(409, lambda: s.upload(p, a.id, v.id, io.BytesIO(b"hello"), 5, v.checksum))
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending_versions = list(pool.map(lambda _: initiate(s, p, a.id), range(2)))
    assert sorted(v.sequence for v in pending_versions) == [2, 3]
    v2 = commit(s, p, a.id, b"second")
    assert v2.sequence == 4 and s.versions(p, a.id)[-1] == v
    stream, size = s.download(p, a.id, v.id)
    with stream:
        assert size == 5 and stream.read() == b"hello"
    with world.sessions.begin() as db:
        with pytest.raises(IntegrityError):
            db.execute(
                update(ArtifactVersion).where(ArtifactVersion.id == v.id).values(filename="new")
            )
    with world.sessions.begin() as db:
        with pytest.raises(IntegrityError):
            db.execute(delete(ArtifactVersion).where(ArtifactVersion.id == v.id))
    s.update_resource(p, a.id, None, a.revision)
    raises(404, lambda: s.download(p, a.id, v.id))
    with world.sessions() as db:
        assert db.get(ArtifactVersion, (p.tenant_id, a.id, v.id)).state == "COMMITTED"
    assert store.exists(ObjectKey(p.tenant_id, a.id, v.id))


def test_missing_corruption_and_cleanup_only_uncommitted(world, store, monkeypatch):  # noqa: F811
    s, p = service(world, store), world.actor
    a = artifact(s, p)
    retained = commit(s, p, a.id)
    pending = initiate(s, p, a.id)
    key = ObjectKey(p.tenant_id, a.id, pending.id)
    # Corrupt physical bytes through test-only provider access; never production API.
    store.client.put_object(Bucket=store.settings.bucket, Key=str(key), Body=b"wrong")
    raises(409, lambda: s.finalize(p, a.id, pending.id))
    store.delete(key)
    raises(503, lambda: s.finalize(p, a.id, pending.id))
    with world.sessions.begin() as db:
        # Test-only time travel; pending identity is immutable in application operations.
        db.execute(text("ALTER TABLE artifact_versions DISABLE TRIGGER guard_artifact_version"))
        db.execute(
            update(ArtifactVersion)
            .where(ArtifactVersion.id == pending.id)
            .values(created_at=datetime.now(UTC) - timedelta(days=2))
        )
        db.execute(text("ALTER TABLE artifact_versions ENABLE TRIGGER guard_artifact_version"))
    assert s.cleanup(p, a.id)[0].outcome == "eligible"
    assert s.metadata(p, a.id, pending.id).state == "PENDING"
    delete_object = store.delete

    def fail_delete(_key):
        raise StorageError(Failure.TRANSIENT)

    monkeypatch.setattr(store, "delete", fail_delete)
    assert s.cleanup(p, a.id, False)[0].outcome == "retry"
    assert s.metadata(p, a.id, pending.id).state == "FAILED"
    monkeypatch.setattr(store, "delete", delete_object)
    assert s.cleanup(p, a.id, False)[0].outcome == "deleted"
    assert s.cleanup(p, a.id, False) == []
    assert s.metadata(p, a.id, retained.id).state == "COMMITTED"
    assert store.exists(ObjectKey(p.tenant_id, a.id, retained.id))


def test_artifact_security_shared_read_revocation_and_tenant(security, store):  # noqa: F811
    w, auth, admin_service, admin, reader, _ = security
    grant_projects(admin_service, admin, reader)
    s = service(w, store, auth)
    a = artifact(s, admin)
    v = commit(s, admin, a.id)
    b = s.create_project(reader, CreateProject(name="Reader"))
    raises(404, lambda: s.download(reader, a.id, v.id))
    raises(404, lambda: s.metadata(reader, a.id, v.id))
    errors = []
    for resource_id in (a.id, uuid4()):
        with pytest.raises(ApplicationError) as denied:
            s.cleanup(reader, resource_id)
        errors.append((denied.value.status_code, denied.value.code, denied.value.message))
    assert errors[0] == errors[1]

    assert s.resources(reader, b.id) == []
    # Sharing administrator must also be member of destination, as in Phase 11.
    s.member(
        reader,
        b.id,
        MemberChange(principal_id=admin.principal_id, role="viewer", expected_revision=1),
    )
    shared = s.share(admin, a.id, ShareChange(project_id=b.id, enabled=True, expected_revision=1))
    file, _ = s.download(reader, a.id, v.id)
    file.close()
    assert s.resources(reader, b.id, shared=True)[0].id == a.id
    raises(
        404,
        lambda: s.initiate(reader, a.id, InitiateUpload(filename="a", size=0, checksum="0" * 64)),
    )
    s.share(
        admin, a.id, ShareChange(project_id=b.id, enabled=False, expected_revision=shared.revision)
    )
    raises(404, lambda: s.download(reader, a.id, v.id))
    outsider = admin.model_copy(update={"tenant_id": uuid4()})
    raises(403, lambda: s.metadata(outsider, a.id, v.id))


def test_api_upload_download_bounds_and_metadata_secrets(world, store):  # noqa: F811
    s, p = service(world, store), world.actor
    a = artifact(s, p)
    with client_for(world) as client:
        v = client.post(
            f"/api/v1/artifacts/{a.id}/uploads",
            json={
                "filename": "file.bin",
                "size": 1100000,
                "checksum": hashlib.sha256(b"a" * 1100000).hexdigest(),
            },
        ).json()
        path = f"/api/v1/artifacts/{a.id}/versions/{v['id']}"
        import asyncio
        from uuid import UUID

        from ontology_platform.artifacts.routes import upload
        from starlette.requests import ClientDisconnect, Request

        async def disconnect():
            messages = iter(
                [
                    {"type": "http.request", "body": b"partial", "more_body": True},
                    {"type": "http.disconnect"},
                ]
            )

            async def receive():
                return next(messages)

            await upload(a.id, UUID(v["id"]), Request({"type": "http"}, receive), p, s)

        with pytest.raises(ClientDisconnect):
            asyncio.run(disconnect())
        assert s.metadata(p, a.id, UUID(v["id"])).state == "PENDING"
        assert not store.exists(ObjectKey(p.tenant_id, a.id, UUID(v["id"])))

        assert client.put(path + "/content", content=b"a" * 1100000).status_code == 200
        assert client.post(path + "/finalize").status_code == 200
        response = client.get(path + "/content")
        assert response.status_code == 200 and response.content == b"a" * 1100000
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-disposition"].startswith("attachment")
        assert not {"bucket", "object_key", "backend"} & set(v)
        assert (
            client.post(
                f"/api/v1/artifacts/{a.id}/uploads",
                json={"filename": "../escape", "size": 0, "checksum": "0" * 64},
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/api/v1/artifacts/{a.id}/uploads",
                json={"filename": "safe", "size": 0, "checksum": "0" * 64, "bucket": "other"},
            ).status_code
            == 422
        )


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://private",
        "https://a/path",
        "file:///etc/passwd",
        "https://u:p@host",
        "https://host?x=1",
    ],
)
def test_config_rejects_unsafe_endpoints(endpoint):
    with pytest.raises(ValidationError):
        StorageSettings(_env_file=None, backend="s3", endpoint=endpoint, development_http=False)


def test_sdk_contract_configuration_errors_and_presign_scope():
    settings = StorageSettings(
        _env_file=None,
        backend="s3",
        access_key="test",
        secret_key="test",
        client_reachable=True,
        endpoint="https://s3.example.test",
        development_http=False,
    )
    store = S3ArtifactStore(settings)
    # Actual installed SDK model, not invented API parameters.
    for op in ("PutObject", "CompleteMultipartUpload"):
        assert (
            "IfNoneMatch" in store.client.meta.service_model.operation_model(op).input_shape.members
        )
    cfg = store.client.meta.config
    assert cfg.connect_timeout == 3 and cfg.read_timeout == 10
    assert cfg.retries["total_max_attempts"] == 3
    key = ObjectKey(uuid4(), uuid4(), uuid4())
    url = store.presign(key)
    assert str(key) in url and ("Expires=" in url or "X-Amz-Expires=60" in url)
    assert "uploadId" not in url
    store.settings = settings.model_copy(update={"client_reachable": False})
    with pytest.raises(StorageError):
        store.presign(key)
    with pytest.raises(StorageError):
        ObjectKey("../escape", uuid4(), uuid4())
    with pytest.raises(ValidationError):
        StorageSettings(_env_file=None, backend="s3", ca_bundle="/does/not/exist")
    with pytest.raises(ValidationError):
        StorageSettings(_env_file=None, backend="s3", attempts=99)
    with pytest.raises(ValidationError) as invalid:
        StorageSettings(
            _env_file=None,
            backend="s3",
            endpoint="file:///invalid",
            access_key="do-not-log-key",
            secret_key="do-not-log-secret",
        )
    assert "do-not-log" not in str(invalid.value)

    for code, category in [
        ("AccessDenied", Failure.ACCESS),
        ("SlowDown", Failure.TRANSIENT),
        ("BadRequest", Failure.PERMANENT),
    ]:
        assert translate(ClientError({"Error": {"Code": code}}, "test")).category == category
    with Stubber(store.client) as stub:
        stub.add_client_error("head_object", service_error_code="SlowDown", http_status_code=503)
        with pytest.raises(StorageError) as exc:
            store.head(key)
        assert exc.value.category == Failure.TRANSIENT


def test_storage_disabled_ontology_remains_available(world):  # noqa: F811
    s = ArtifactService(
        world.sessions, world.registry.authorizer, StorageSettings(backend="disabled"), None
    )
    p = s.create_project(world.actor, CreateProject(name="No storage"))
    raises(503, lambda: s.create(world.actor, p.id, CreateArtifact(name="a")))
    assert s.get_project(world.actor, p.id).id == p.id


def test_real_http_retry_timeout_and_tls_failure():
    """Exercise botocore transport behavior against a bounded local failing provider."""
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        calls = 0
        mode = "retry"

        def log_message(self, *_args):
            pass

        def do_HEAD(self):
            Handler.calls += 1
            if Handler.mode == "timeout":
                time.sleep(1.5)
            status = 503 if Handler.mode == "retry" and Handler.calls < 3 else 200
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = StorageSettings(
            _env_file=None,
            backend="s3",
            endpoint=f"http://127.0.0.1:{server.server_port}",
            access_key="test",
            secret_key="test",
            development_http=True,
            read_seconds=1,
            attempts=3,
        )
        store = S3ArtifactStore(settings)
        key = ObjectKey(uuid4(), uuid4(), uuid4())
        assert store.head(key).size == 0 and Handler.calls == 3
        Handler.calls, Handler.mode = 0, "timeout"
        store = S3ArtifactStore(settings.model_copy(update={"attempts": 1}))
        start = time.monotonic()
        with pytest.raises(StorageError) as exc:
            store.head(key)
        assert exc.value.category == Failure.TRANSIENT
        assert Handler.calls == 1 and time.monotonic() - start < 2
        tls = settings.model_copy(
            update={
                "endpoint": settings.endpoint.replace("http:", "https:"),
                "development_http": False,
                "attempts": 1,
            }
        )
        with pytest.raises(StorageError) as exc:
            S3ArtifactStore(tls).head(key)
        assert exc.value.category == Failure.CONFIGURATION
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_upgrade_phase11_preserves_governed_resources_and_tenant_fks(historical_database, store):  # noqa: F811
    from alembic import command
    from alembic.config import Config
    from ontology_platform.db.models import Resource
    from test_phase1 import ROOT, active
    from test_projects import resource

    w = make_world(historical_database)
    active(w)
    projects = service(w, store)
    a = projects.create_project(w.actor, CreateProject(name="Existing Project"))
    old = resource(projects, w.actor, a.id)
    migrate(w.engine)
    assert projects.get_resource(w.actor, old.id) == old
    artifact = projects.create(w.actor, a.id, CreateArtifact(name="New artifact"))
    pending = initiate(projects, w.actor, artifact.id)
    with w.sessions.begin() as db:
        with pytest.raises(IntegrityError):
            db.add(
                ArtifactVersion(
                    tenant_id=uuid4(),
                    artifact_id=artifact.id,
                    id=uuid4(),
                    sequence=1,
                    backend="s3",
                    bucket="test",
                    object_key="invalid",
                    size=0,
                    checksum="0" * 64,
                    filename="a",
                    created_by="test",
                )
            )
            db.flush()
    with w.sessions.begin() as db:
        with pytest.raises(IntegrityError):
            db.execute(update(Resource).where(Resource.id == old.id).values(ontology_id=None))
    config = Config(str(ROOT / "alembic.ini"))
    with w.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.check(config)
    with pytest.raises(RuntimeError, match="forward-only"):
        migrate(w.engine, "0018_projects", downgrade=True)
    assert projects.metadata(w.actor, artifact.id, pending.id).state == "PENDING"
