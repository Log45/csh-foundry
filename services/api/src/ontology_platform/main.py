from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException

from ontology_platform.api.v1.routes import router
from ontology_platform.config import Settings, get_settings
from ontology_platform.db.governance import SCHEMA_REVISION
from ontology_platform.db.session import make_engine
from ontology_platform.dependencies import get_session
from ontology_platform.errors import ApplicationError
from ontology_platform.queries.cursor import CursorCodec
from ontology_platform.queries.routes import router as query_router
from ontology_platform.security.local import LocalAuthorizer


class Health(BaseModel):
    status: str


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings or get_settings()
    engine = make_engine(configuration)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(
        title="Operational Ontology Platform",
        version="0.0.1",
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json",
        docs_url="/docs",
    )
    app.include_router(router)
    app.include_router(query_router)
    app.state.query_cursors = CursorCodec(
        configuration.query_cursor_secret.get_secret_value().encode()
        if configuration.query_cursor_secret
        else None
    )
    app.state.authorizer = LocalAuthorizer(configuration)
    app.state.settings = configuration
    app.state.engine = engine
    app.state.sessions = sessionmaker(engine, expire_on_commit=False)

    @app.exception_handler(ApplicationError)
    async def application_error(request: Request, exc: ApplicationError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_request", "message": "Request validation failed"}},
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": "http_error", "message": str(exc.detail)}},
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "An internal error occurred"}},
        )

    @app.get("/health/live", response_model=Health, tags=["health"])
    def live() -> Health:
        return Health(status="ok")

    @app.get("/health/ready", response_model=Health, tags=["health"])
    def ready(session: Annotated[Session, Depends(get_session)]) -> Health:
        try:
            session.execute(text("SELECT 1"))
            revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
            if revision != SCHEMA_REVISION:
                raise ApplicationError("database_not_ready", "Database migration required", 503)
        except SQLAlchemyError as exc:
            raise ApplicationError("database_unavailable", "Database is unavailable", 503) from exc
        return Health(status="ready")

    return app
