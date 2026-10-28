from typing import Annotated

from fastapi import Depends
from fastapi.testclient import TestClient
from ontology_platform.config import Settings
from ontology_platform.dependencies import get_principal, get_session
from ontology_platform.main import create_app
from ontology_platform.security.interfaces import Principal
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError


def test_health_openapi_and_fail_closed():
    app = create_app(
        Settings(database_url=SecretStr("postgresql+psycopg://localhost/unused"), _env_file=None)
    )

    @app.get("/protected")
    def protected(principal: Annotated[Principal, Depends(get_principal)]):
        return principal

    def unavailable():
        raise OperationalError("", {}, Exception("private details"))
        yield

    app.dependency_overrides[get_session] = unavailable
    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        # Dependency failures are sanitized by the catch-all handler.
        assert client.get("/protected").status_code == 401
        assert client.get("/missing").json()["error"]["code"] == "http_error"
        assert "/health/ready" in client.get("/api/v1/openapi.json").json()["paths"]


def test_readiness_database_error():
    app = create_app(
        Settings(database_url=SecretStr("postgresql+psycopg://localhost/unused"), _env_file=None)
    )

    class BrokenSession:
        def execute(self, statement):
            raise OperationalError("", {}, Exception("private password"))

    app.dependency_overrides[get_session] = lambda: BrokenSession()
    with TestClient(app) as client:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert "private" not in response.text
        assert response.json()["error"]["code"] == "database_unavailable"
