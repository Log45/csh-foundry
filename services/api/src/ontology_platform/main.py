import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ontology_platform.actions.limits import ActionPayloadLimit
from ontology_platform.actions.routes import router as action_router
from ontology_platform.api.v1.routes import router
from ontology_platform.applications.routes import router as application_router
from ontology_platform.artifacts.config import StorageSettings
from ontology_platform.artifacts.routes import router as artifact_router
from ontology_platform.artifacts.s3 import S3ArtifactStore
from ontology_platform.automations.routes import router as automation_router
from ontology_platform.branching.routes import router as branch_router
from ontology_platform.config import Settings, get_settings
from ontology_platform.datasets.routes import router as dataset_router
from ontology_platform.db.governance import SCHEMA_REVISION
from ontology_platform.db.session import make_engine, require_runtime_role
from ontology_platform.dependencies import get_session
from ontology_platform.errors import ApplicationError
from ontology_platform.functions.routes import router as function_router
from ontology_platform.ingestion.catalog import SourceCatalog
from ontology_platform.ingestion.routes import router as ingestion_router
from ontology_platform.interoperability.routes import router as interchange_router
from ontology_platform.mappings.routes import router as mapping_router
from ontology_platform.media.routes import router as media_router
from ontology_platform.observability.routes import router as observability_router
from ontology_platform.operations import RequestTelemetry, Telemetry, TransportBounds
from ontology_platform.pipelines.routes import router as pipeline_router
from ontology_platform.projects.routes import router as project_router
from ontology_platform.queries.cursor import CursorCodec
from ontology_platform.queries.routes import router as query_router
from ontology_platform.sdk.routes import router as sdk_router
from ontology_platform.security.browser import BrowserStore
from ontology_platform.security.browser import router as browser_router
from ontology_platform.security.local import LocalAuthorizer
from ontology_platform.security.oidc import OIDCVerifier
from ontology_platform.security.routes import router as security_router
from ontology_platform.security.service import PlatformAuthorizer
from ontology_platform.semantic.routes import router as semantic_router


class Health(BaseModel):
    status: str


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings or get_settings()
    if configuration.environment == "production":
        import logging
        import sys

        logger = logging.getLogger("foundry.operations")
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    engine = make_engine(configuration)
    audit_engine = make_engine(configuration, audit=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            if configuration.environment == "production":
                require_runtime_role(app.state.sessions)
            if configuration.auth_mode == "oidc":
                # Startup must fail rather than fall back to development identity.
                import asyncio

                await asyncio.to_thread(app.state.oidc.warm)
            yield
        finally:
            if hasattr(app.state, "oidc"):
                app.state.oidc.client.close()
            engine.dispose()
            audit_engine.dispose()

    app = FastAPI(
        title="Operational Ontology Platform",
        version="0.0.1",
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json",
        docs_url="/docs",
    )
    app.add_middleware(ActionPayloadLimit)
    app.add_middleware(
        ActionPayloadLimit,
        paths=("/sources", "/mappings", "/ingestion/runs"),
        code="ingestion_payload_too_large",
        message="Ingestion payload exceeds 64 KiB",
    )
    app.include_router(router)
    app.include_router(project_router)
    app.include_router(application_router)
    app.add_middleware(
        ActionPayloadLimit,
        paths=("/applications",),
        methods=("POST", "PUT"),
        code="application_payload_too_large",
        message="Application payload exceeds 64 KiB",
    )
    app.include_router(artifact_router)
    app.include_router(dataset_router)
    app.include_router(pipeline_router)
    app.include_router(observability_router)
    app.add_middleware(
        ActionPayloadLimit,
        paths=("/pipelines",),
        methods=("POST", "PUT"),
        code="pipeline_payload_too_large",
        message="Pipeline payload exceeds 512 KiB",
        max_bytes=524288,
    )
    app.include_router(mapping_router)
    app.include_router(media_router)
    app.include_router(function_router)
    app.include_router(automation_router)
    app.add_middleware(
        ActionPayloadLimit,
        paths=("/media-sets", "/functions", "/automations"),
        code="governed_payload_too_large",
        message="Governed request exceeds 64 KiB",
    )
    app.add_middleware(
        ActionPayloadLimit,
        paths=("/artifacts", "/datasets"),
        code="artifact_payload_too_large",
        message="Artifact metadata exceeds 64 KiB",
    )
    artifact_settings = StorageSettings(_secrets_dir=os.environ.get("FOUNDRY_SECRETS_DIRECTORY"))
    if (
        configuration.environment == "production"
        and artifact_settings.backend == "s3"
        and artifact_settings.development_http
    ):
        raise ValueError("Production artifact storage requires TLS")
    app.state.artifact_settings = artifact_settings
    app.state.artifact_store = (
        S3ArtifactStore(artifact_settings) if artifact_settings.backend == "s3" else None
    )
    app.add_middleware(
        ActionPayloadLimit,
        paths=("/projects", "/resources"),
        code="project_payload_too_large",
        message="Project request exceeds 64 KiB",
    )
    app.include_router(branch_router)
    app.include_router(sdk_router)
    app.add_middleware(
        ActionPayloadLimit,
        paths=("/sdk",),
        code="sdk_payload_too_large",
        message="SDK request exceeds 64 KiB",
    )
    app.add_middleware(
        ActionPayloadLimit,
        paths=("/branches",),
        code="branch_payload_too_large",
        message="Branch request exceeds 64 KiB",
    )
    app.include_router(query_router)
    app.include_router(action_router)
    app.include_router(ingestion_router)
    app.include_router(semantic_router)
    app.include_router(interchange_router)
    app.include_router(security_router)
    app.include_router(browser_router)
    app.add_middleware(
        ActionPayloadLimit,
        paths=("/internal/",),
        code="session_payload_too_large",
        message="Session payload exceeds 64 KiB",
    )
    if configuration.allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(configuration.allowed_hosts))
    app.add_middleware(
        ActionPayloadLimit,
        paths=("/interchange/",),
        code="import_payload_too_large",
        message="Import request exceeds 64 KiB",
    )
    app.add_middleware(
        ActionPayloadLimit,
        paths=("/semantic",),
        code="semantic_payload_too_large",
        message="Semantic request exceeds 64 KiB",
    )
    app.state.ingestion_catalog = SourceCatalog.from_json(configuration.ingestion_catalog_json)
    app.state.query_cursors = CursorCodec(
        configuration.query_cursor_secret.get_secret_value().encode()
        if configuration.query_cursor_secret
        else None
    )
    app.state.settings = configuration
    app.state.engine = engine
    app.state.sessions = sessionmaker(engine, expire_on_commit=False)
    app.state.browser_store = BrowserStore(app.state.sessions, configuration)
    app.state.telemetry = Telemetry()
    app.add_middleware(TransportBounds, transfer_deadline=artifact_settings.transfer_seconds)
    app.add_middleware(
        RequestTelemetry, telemetry=app.state.telemetry, diagnostic=configuration.diagnostic_timing
    )
    app.state.authorizer = (
        PlatformAuthorizer(
            app.state.sessions,
            test_mode=configuration.auth_mode == "test",
            audit_sessions=sessionmaker(audit_engine),
        )
        if configuration.auth_mode in {"oidc", "test"}
        else LocalAuthorizer(configuration)
    )
    if configuration.auth_mode == "oidc":
        app.state.oidc = OIDCVerifier(
            configuration.oidc_providers,
            ca_bundle=configuration.oidc_ca_bundle,
            backchannel_port=configuration.oidc_backchannel_port,
        )
    app.add_middleware(
        ActionPayloadLimit,
        paths=("/security",),
        code="security_payload_too_large",
        message="Security request exceeds 64 KiB",
    )

    @app.exception_handler(ApplicationError)
    async def application_error(request: Request, exc: ApplicationError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
            headers={"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None,
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

    @app.get("/internal/metrics", include_in_schema=False)
    def metrics(request: Request) -> PlainTextResponse:
        app.state.browser_store.authenticate(request.headers.get("authorization"))
        return PlainTextResponse(
            app.state.telemetry.render(), media_type="text/plain; version=0.0.4"
        )

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
