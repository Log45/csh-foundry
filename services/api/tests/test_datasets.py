"""Independent datasets: full-content parser and real PostgreSQL/MinIO governance."""

import csv
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time
from decimal import Decimal
from uuid import uuid4

import polars as pl
import pytest
from alembic import command
from alembic.config import Config
from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.artifacts.service import ArtifactService
from ontology_platform.datasets.contracts import InitiateDataset
from ontology_platform.datasets.parser import MAX_BYTES, InvalidDataset, parse, safe, validate
from ontology_platform.datasets.service import DatasetService
from ontology_platform.db.models import DatasetVersion
from ontology_platform.projects.contracts import (
    CreateProject,
    MemberChange,
    ShareChange,
    UpdateResource,
)
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from test_artifacts import store  # noqa: F401
from test_phase1 import ROOT, client_for, database, historical_database, world  # noqa: F401
from test_projects import grant_projects, raises
from test_security_platform import security  # noqa: F401


def make_service(w, backend, auth=None):
    return DatasetService(w.sessions, auth or w.registry.authorizer, backend.settings, backend)


def dataset(s, p):
    project = s.create_project(p, CreateProject(name="Dataset project " + uuid4().hex))
    return s.create(p, project.id, CreateArtifact(name="Independent data"))


def initiate(s, p, key, data, format="csv"):
    return s.initiate_dataset(
        p,
        key,
        InitiateDataset(
            filename="source",
            size=len(data),
            checksum=hashlib.sha256(data).hexdigest(),
            format=format,
        ),
    )


def commit(s, p, key, data=b"id,value\n1,hello\n2,\n", format="csv"):
    v = initiate(s, p, key, data, format)
    s.upload(p, key, v.id, io.BytesIO(data), len(data), v.checksum)
    return s.finalize_dataset(p, key, v.id)


@pytest.mark.parametrize(
    "format,data",
    [
        ("csv", b"id,value\n1,hello\n2,\n"),
        ("json", b'[{"id":1,"value":"hello"},{"id":2,"value":null}]'),
        ("ndjson", b'{"id":1,"value":"hello"}\n{"id":2,"value":null}'),
    ],
)
def test_full_content_schema_and_nulls(format, data):
    result = parse(data, format)
    assert [c["name"] for c in result["schema"]] == ["id", "value"]
    assert result["row_count"] == 2
    assert result["preview"] == [[1, "hello"], [2, None]]
    assert result["schema"][1]["nullable"]


@pytest.mark.parametrize(
    "format,data",
    [
        ("csv", b"a,a\n1,2"),
        ("csv", b"a\n1,2"),
        ("csv", b"a\n\xff"),
        ("csv", b'a\n"unclosed'),
        ("json", b'[{"a":1,"a":2}]'),
        ("json", b'[{"a":1},{"b":2}]'),
        ("json", b'[{"a":1},{"a":"x"}]'),
        ("json", b'{"a":1}'),
        ("json", b"[{}]"),
        ("ndjson", b"{}"),
        ("ndjson", b"[1,2]"),
        ("parquet", b"PAR1broken"),
        ("pickle", b"cos\nsystem\n"),
        ("json", b'[{"a":NaN}]'),
        ("json", json.dumps([{"a": [[[[[[[[[[1]]]]]]]]]]}]).encode()),
        ("csv", b"a\n" + b"x" * 65537),
    ],
)
def test_rejects_invalid_content(format, data):
    with pytest.raises((ValueError, csv.Error, pl.exceptions.PolarsError, OSError)):
        parse(data, format)


def test_empty_mixed_types_and_bounded_preview():
    assert parse(b"[]", "json")["schema"] == []
    assert parse(b"", "ndjson")["row_count"] == 0
    assert parse(b"a,b\n", "csv")["column_count"] == 2
    with pytest.raises(InvalidDataset):
        parse(b"", "csv")
    mixed = parse(b"a\n1\nx\n", "csv")
    assert mixed["schema"][0]["logical_type"] == "String"
    assert len(parse(b"a\n" + b"1\n" * 1000, "csv")["preview"]) == 100
    with pytest.raises(InvalidDataset):
        parse(b"x" * (MAX_BYTES + 1), "csv")
    with pytest.raises(InvalidDataset):
        parse(b"a\n" + b"1\n" * 100001, "csv")


def test_parquet_rich_types_and_serialization():
    frame = pl.DataFrame(
        {
            "date": [date(2026, 1, 1)],
            "decimal": [Decimal("1.20")],
            "binary": [b"abc"],
            "nested": [[1, 2]],
            "struct": [{"ok": True}],
            "time": [time(12, 30)],
            "timestamp": [datetime(2026, 1, 1)],
        }
    )
    data = io.BytesIO()
    frame.write_parquet(data)
    result = parse(data.getvalue(), "parquet")
    assert result["preview"][0][:4] == ["2026-01-01", "1.20", {"base64": "YWJj"}, [1, 2]]
    assert "Decimal" in result["schema"][1]["logical_type"]
    assert result["source_schema"]
    assert safe(None) is None


def test_spawned_validation_sanitizes_errors():
    assert validate(io.BytesIO(b"a\n1"), "csv")["row_count"] == 1
    result = validate(io.BytesIO(b"a\nsecret,private"), "csv")
    assert result["error"] == "invalid_dataset"
    assert "secret" not in json.dumps(result)


def test_dataset_lifecycle_recovery_immutability_and_drift(world, store):  # noqa: F811
    s, p = make_service(world, store), world.actor
    d = dataset(s, p)
    v = commit(s, p, d.id)
    assert v.state == v.artifact_state == "COMMITTED"
    assert s.finalize_dataset(p, d.id, v.id) == v
    assert s.preview(p, d.id, v.id, 1).rows == [[1, "hello"]]
    original = s.preview(p, d.id, v.id)
    renamed = s.update_resource(
        p,
        d.id,
        UpdateResource(
            name="Renamed", description="new", folder_id=None, expected_revision=d.revision
        ),
        d.revision,
    )
    assert renamed.id == d.id
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = list(pool.map(lambda _: initiate(s, p, d.id, b"a\n1"), range(2)))
    assert sorted(item.sequence for item in pending) == [2, 3]
    raises(409, lambda: s.preview(p, d.id, pending[0].id))
    raises(503, lambda: s.finalize_dataset(p, d.id, pending[0].id))
    # Durable artifact commit before dataset publication, followed by service restart.
    data = b"new\ntrue"
    waiting = initiate(s, p, d.id, data)
    s.upload(p, d.id, waiting.id, io.BytesIO(data), len(data), waiting.checksum)
    s.finalize(p, d.id, waiting.id)
    restarted = make_service(world, store)
    second = restarted.finalize_dataset(p, d.id, waiting.id)
    assert second.result["schema"] != v.result["schema"]
    assert s.preview(p, d.id, v.id) == original
    failed = commit(s, p, d.id, b"a,a\n1,2")
    assert failed.state == "FAILED" and failed.artifact_state == "COMMITTED"
    assert s.finalize_dataset(p, d.id, failed.id) == failed
    raises(409, lambda: s.preview(p, d.id, failed.id))
    for operation in [update(DatasetVersion).values(format="json"), delete(DatasetVersion)]:
        with world.sessions.begin() as db:
            with pytest.raises(IntegrityError):
                db.execute(operation.where(DatasetVersion.id == v.id))
    with world.engine.begin() as connection:
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = connection
        command.check(config)
    s.update_resource(p, d.id, None, renamed.revision)
    raises(404, lambda: s.preview(p, d.id, v.id))


def test_dataset_api_and_artifact_boundary(world, store):  # noqa: F811
    s, p = make_service(world, store), world.actor
    d = dataset(s, p)
    with client_for(world) as client:
        data = b"a\n1\n2"
        response = client.post(
            f"/api/v1/datasets/{d.id}/uploads",
            json={
                "filename": "source.csv",
                "size": len(data),
                "checksum": hashlib.sha256(data).hexdigest(),
                "format": "csv",
            },
        )
        assert response.status_code == 201, response.text
        v = response.json()
        path = f"/api/v1/datasets/{d.id}/versions/{v['id']}"
        assert client.put(path + "/content", content=data).status_code == 200
        assert client.post(path + "/finalize").json()["state"] == "COMMITTED"
        assert client.get(path + "/schema").json()[0]["name"] == "a"
        assert client.get(path + "/preview?limit=1").json()["rows"] == [[1]]
        assert client.get(path + "/preview?limit=101").status_code == 422
        assert client.get(path + "/content").content == data
        assert client.get(f"/api/v1/artifacts/{d.id}/versions/{v['id']}/content").status_code == 404
        assert not {"bucket", "object_key", "backend"} & set(v)


def test_dataset_sharing_revocation_and_tenant_isolation(security, store):  # noqa: F811
    w, auth, administration, owner, other, _ = security
    grant_projects(administration, owner, other)
    outsider = owner.model_copy(update={"tenant_id": uuid4()})
    s = make_service(w, store, auth)
    d = dataset(s, owner)
    v = commit(s, owner, d.id)
    consumer = s.create_project(owner, CreateProject(name="Consumer"))
    consumer = s.member(
        owner,
        consumer.id,
        MemberChange(
            principal_id=other.principal_id, role="viewer", expected_revision=consumer.revision
        ),
    )
    raises(404, lambda: s.preview(other, d.id, v.id))
    raises(403, lambda: s.dataset_metadata(outsider, d.id, v.id))
    s.share(
        owner, d.id, ShareChange(project_id=consumer.id, enabled=True, expected_revision=d.revision)
    )
    assert s.preview(other, d.id, v.id).rows
    raises(404, lambda: initiate(s, other, d.id, b"a\n1"))
    generic = ArtifactService(w.sessions, auth, store.settings, store)
    raises(404, lambda: generic.download(other, d.id, v.id))
    current = s.get_resource(owner, d.id)
    s.share(
        owner,
        d.id,
        ShareChange(project_id=consumer.id, enabled=False, expected_revision=current.revision),
    )
    raises(404, lambda: s.preview(other, d.id, v.id))
    raises(404, lambda: s.download(other, d.id, v.id))


@pytest.mark.parametrize("format", ["csv", "json", "ndjson", "parquet"])
def test_real_upload_formats(world, store, format):  # noqa: F811
    s, p = make_service(world, store), world.actor
    d = dataset(s, p)
    data = {
        "csv": b"id,value\n1,x\n2,\n",
        "json": b'[{"id":1,"value":"x"},{"id":2,"value":null}]',
        "ndjson": b'{"id":1,"value":"x"}\n{"id":2,"value":null}',
    }
    if format == "parquet":
        file = io.BytesIO()
        pl.DataFrame({"id": [1, 2], "value": ["x", None]}).write_parquet(file)
        content = file.getvalue()
    else:
        content = data[format]
    v = commit(s, p, d.id, content, format)
    assert v.state == "COMMITTED"
    assert s.preview(p, d.id, v.id).rows == [[1, "x"], [2, None]]
    with s.download(p, d.id, v.id)[0] as source:
        assert source.read() == content


def test_publication_rollback_retry_and_concurrent_finalize(world, store, monkeypatch):  # noqa: F811
    s, p = make_service(world, store), world.actor
    d = dataset(s, p)
    data = b"id\n1"
    v = initiate(s, p, d.id, data)
    s.upload(p, d.id, v.id, io.BytesIO(data), len(data), v.checksum)
    audit = s.audit

    def fail_publication(db, actor, operation, *args):
        if operation == "dataset_validation_committed":
            raise RuntimeError("Simulated database publication failure")
        audit(db, actor, operation, *args)

    monkeypatch.setattr(s, "audit", fail_publication)
    with pytest.raises(RuntimeError, match="publication failure"):
        s.finalize_dataset(p, d.id, v.id)
    assert s.dataset_metadata(p, d.id, v.id).state == "PENDING"
    assert s.dataset_metadata(p, d.id, v.id).artifact_state == "COMMITTED"
    monkeypatch.setattr(s, "audit", audit)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: s.finalize_dataset(p, d.id, v.id), range(2)))
    assert results[0] == results[1]
    assert results[0].state == "COMMITTED"


def test_direct_database_reference_guards(world, store):  # noqa: F811
    from datetime import UTC

    s, p = make_service(world, store), world.actor
    d = dataset(s, p)
    v = initiate(s, p, d.id, b"id\n1")
    # Dataset publication requires a committed artifact even for direct SQL writes.
    with world.sessions.begin() as db:
        with pytest.raises(IntegrityError):
            db.execute(
                update(DatasetVersion)
                .where(DatasetVersion.id == v.id)
                .values(state="COMMITTED", finalized_at=datetime.now(UTC), result={"row_count": 1})
            )
    for tenant, resource in [(uuid4(), d.id), (p.tenant_id, uuid4())]:
        with world.sessions.begin() as db:
            with pytest.raises(IntegrityError):
                db.add(
                    DatasetVersion(tenant_id=tenant, artifact_id=resource, id=v.id, format="csv")
                )
                db.flush()


def test_dataset_move_and_disconnect(world, store):  # noqa: F811
    import asyncio

    from ontology_platform.artifacts.routes import upload
    from ontology_platform.projects.contracts import CreateFolder
    from starlette.requests import ClientDisconnect, Request

    s, p = make_service(world, store), world.actor
    d = dataset(s, p)
    folder = s.create_folder(p, d.project_id, CreateFolder(name="Raw"))
    moved = s.update_resource(
        p,
        d.id,
        UpdateResource(name="Moved", folder_id=folder.id, expected_revision=d.revision),
        d.revision,
    )
    assert moved.id == d.id and moved.folder_id == folder.id
    v = initiate(s, p, d.id, b"id\n1")

    async def disconnect():
        messages = iter(
            [
                {"type": "http.request", "body": b"id", "more_body": True},
                {"type": "http.disconnect"},
            ]
        )

        async def receive():
            return next(messages)

        await upload(d.id, v.id, Request({"type": "http"}, receive), p, s)

    with pytest.raises(ClientDisconnect):
        asyncio.run(disconnect())
    assert s.dataset_metadata(p, d.id, v.id).state == "PENDING"
    raises(503, lambda: s.finalize_dataset(p, d.id, v.id))


def test_capacity_and_deadline_are_bounded(monkeypatch):
    from ontology_platform.datasets import parser
    from ontology_platform.errors import ApplicationError

    parser.PARSERS.acquire()
    parser.PARSERS.acquire()
    try:
        with pytest.raises(ApplicationError) as busy:
            parser.validate(io.BytesIO(b"a\n1"), "csv")
        assert busy.value.code == "validation_capacity" and busy.value.status_code == 503
    finally:
        parser.PARSERS.release()
        parser.PARSERS.release()
    # An expired deadline kills and joins the actual spawned child without publishing data.
    monkeypatch.setattr(parser, "WALL_SECONDS", 0)
    assert parser.validate(io.BytesIO(b"a\n1"), "csv")["error"] == "validation_failed"


def test_preview_never_reopens_storage(world, store, monkeypatch):  # noqa: F811
    s, p = make_service(world, store), world.actor
    d = dataset(s, p)
    v = commit(s, p, d.id)

    def no_storage():
        raise AssertionError("Preview must use the bounded committed cache")

    monkeypatch.setattr(s, "storage", no_storage)
    assert s.preview(p, d.id, v.id).rows == [[1, "hello"], [2, None]]


def test_upgrade_from_phase12_retains_committed_artifacts(historical_database, store):  # noqa: F811
    from test_artifacts import commit as commit_artifact
    from test_phase1 import make_world, migrate

    engine, _, _ = historical_database
    migrate(engine, "0019_artifacts")
    w = make_world(historical_database)
    s = ArtifactService(w.sessions, w.registry.authorizer, store.settings, store)
    p = w.actor
    project = s.create_project(p, CreateProject(name="Before datasets"))
    resource = s.create(p, project.id, CreateArtifact(name="Retained bytes"))
    version = commit_artifact(s, p, resource.id)
    migrate(engine)
    assert s.get_resource(p, resource.id) == resource
    assert s.metadata(p, resource.id, version.id) == version
    with s.download(p, resource.id, version.id)[0] as source:
        assert source.read() == b"hello"
    datasets = make_service(w, store)
    dataset_resource = datasets.create(p, project.id, CreateArtifact(name="New dataset"))
    assert commit(datasets, p, dataset_resource.id).state == "COMMITTED"


def test_bom_duplicate_headers_and_primitive_parquet_types():
    assert parse(b"\xef\xbb\xbfa\n1", "csv")["schema"][0]["name"] == "a"
    with pytest.raises(InvalidDataset):
        parse(b"\xef\xbb\xbfa,a\n1,2", "csv")
    frame = pl.DataFrame(
        {
            "signed": pl.Series([-1], dtype=pl.Int8),
            "unsigned": pl.Series([255], dtype=pl.UInt8),
            "float": [1.5],
            "bool": [True],
            "null": [None],
        }
    )
    content = io.BytesIO()
    frame.write_parquet(content)
    result = parse(content.getvalue(), "parquet")
    assert [c["logical_type"] for c in result["schema"]] == [
        "Int8",
        "UInt8",
        "Float64",
        "Boolean",
        "Null",
    ]
    assert result["preview"] == [[-1, 255, 1.5, True, None]]


def test_dataset_api_streams_over_one_megabyte(world, store):  # noqa: F811
    s, p = make_service(world, store), world.actor
    d = dataset(s, p)
    data = b"a\n" + b"long string value\n" * 65000
    assert len(data) > 1024 * 1024
    v = initiate(s, p, d.id, data)
    with client_for(world) as client:
        path = f"/api/v1/datasets/{d.id}/versions/{v.id}"
        assert client.put(path + "/content", content=data).status_code == 200
        result = client.post(path + "/finalize")
        assert result.status_code == 200 and result.json()["state"] == "COMMITTED"
        assert result.json()["result"]["row_count"] == 65000
