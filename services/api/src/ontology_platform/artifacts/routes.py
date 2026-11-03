import hashlib
import tempfile
from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from ontology_platform.artifacts.contracts import (
    ArtifactVersionView,
    Cleanup,
    CleanupResult,
    CreateArtifact,
    InitiateUpload,
    PresignedAccess,
)
from ontology_platform.artifacts.service import ArtifactService
from ontology_platform.errors import ApplicationError
from ontology_platform.projects.contracts import ResourceView
from ontology_platform.projects.routes import Actor, Limit, Offset

router = APIRouter(prefix="/api/v1", tags=["artifacts"])


def service(request: Request) -> ArtifactService:
    return ArtifactService(
        request.app.state.sessions,
        request.app.state.authorizer,
        request.app.state.artifact_settings,
        request.app.state.artifact_store,
    )


Service = Annotated[ArtifactService, Depends(service)]


@router.post("/projects/{project_id}/artifacts", response_model=ResourceView, status_code=201)
def create(project_id: UUID, body: CreateArtifact, actor: Actor, svc: Service) -> ResourceView:
    return svc.create(actor, project_id, body)


@router.post(
    "/artifacts/{artifact_id}/uploads", response_model=ArtifactVersionView, status_code=201
)
def initiate(
    artifact_id: UUID, body: InitiateUpload, actor: Actor, svc: Service
) -> ArtifactVersionView:
    return svc.initiate(actor, artifact_id, body)


@router.put(
    "/artifacts/{artifact_id}/versions/{version_id}/content",
    response_model=ArtifactVersionView,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload(
    artifact_id: UUID, version_id: UUID, request: Request, actor: Actor, svc: Service
) -> ArtifactVersionView:
    # Authenticate and authorize before consuming the body. Repeat authorization at transfer.
    pending = await run_in_threadpool(svc.prepare_upload, actor, artifact_id, version_id)
    with tempfile.TemporaryFile(mode="w+b") as source:
        digest, size = hashlib.sha256(), 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > min(svc.settings.max_bytes, pending.size):
                raise ApplicationError("upload_too_large", "Artifact exceeds upload limit", 413)
            digest.update(chunk)
            await run_in_threadpool(source.write, chunk)
        source.seek(0)
        return await run_in_threadpool(
            svc.upload, actor, artifact_id, version_id, source, size, digest.hexdigest()
        )


@router.post(
    "/artifacts/{artifact_id}/versions/{version_id}/finalize", response_model=ArtifactVersionView
)
def finalize(
    artifact_id: UUID, version_id: UUID, actor: Actor, svc: Service
) -> ArtifactVersionView:
    return svc.finalize(actor, artifact_id, version_id)


@router.get("/artifacts/{artifact_id}/versions", response_model=list[ArtifactVersionView])
def versions(
    artifact_id: UUID, actor: Actor, svc: Service, limit: Limit = 50, offset: Offset = 0
) -> list[ArtifactVersionView]:
    return svc.versions(actor, artifact_id, limit, offset)


@router.get("/artifacts/{artifact_id}/versions/{version_id}", response_model=ArtifactVersionView)
def metadata(
    artifact_id: UUID, version_id: UUID, actor: Actor, svc: Service
) -> ArtifactVersionView:
    return svc.metadata(actor, artifact_id, version_id)


@router.get("/artifacts/{artifact_id}/versions/{version_id}/content")
def download(artifact_id: UUID, version_id: UUID, actor: Actor, svc: Service) -> StreamingResponse:
    file, size = svc.download(actor, artifact_id, version_id)

    def chunks() -> Iterator[bytes]:
        try:
            while data := file.read(65536):
                yield data
        finally:
            file.close()

    return StreamingResponse(
        chunks(),
        media_type="application/octet-stream",
        headers={
            "Content-Length": str(size),
            "Content-Disposition": 'attachment; filename="artifact.bin"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/artifacts/{artifact_id}/versions/{version_id}/presign", response_model=PresignedAccess
)
def presign(artifact_id: UUID, version_id: UUID, actor: Actor, svc: Service) -> PresignedAccess:
    return svc.presigned(actor, artifact_id, version_id)


@router.post("/artifacts/{artifact_id}/cleanup", response_model=list[CleanupResult])
def cleanup(artifact_id: UUID, body: Cleanup, actor: Actor, svc: Service) -> list[CleanupResult]:
    return svc.cleanup(actor, artifact_id, body.dry_run)
