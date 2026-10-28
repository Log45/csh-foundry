import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from ontology_platform.config import Settings
from ontology_platform.db.governance import SCHEMA_REVISION
from ontology_platform.db.models import Tenant
from ontology_platform.db.session import make_engine, transaction
from ontology_platform.main import create_app
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker


@pytest.mark.integration
def test_database_transaction_and_readiness():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("NOT RUN: set TEST_DATABASE_URL to a migrated disposable PostgreSQL database")
    settings = Settings(database_url=SecretStr(url), _env_file=None)
    engine = make_engine(settings)
    factory = sessionmaker(engine)
    tenant = uuid4()
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
                == SCHEMA_REVISION
            )
        with transaction(factory) as session:
            session.add(Tenant(id=tenant, name="test"))
        with factory() as session:
            assert session.scalar(select(Tenant.name).where(Tenant.id == tenant)) == "test"
        rollback_id = uuid4()
        with pytest.raises(RuntimeError), transaction(factory) as session:
            session.add(Tenant(id=rollback_id, name="rolled back"))
            session.flush()
            raise RuntimeError("rollback")
        with factory() as session:
            assert session.get(Tenant, rollback_id) is None
        with TestClient(create_app(settings)) as client:
            assert client.get("/health/ready").json() == {"status": "ready"}
    finally:
        with transaction(factory) as session:
            row = session.get(Tenant, tenant)
            if row:
                session.delete(row)
        engine.dispose()
