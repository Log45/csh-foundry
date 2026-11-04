from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import JsonValue
from starlette.responses import StreamingResponse

from ontology_platform.artifacts import routes as transport
from ontology_platform.artifacts.contracts import (
    ArtifactVersionView,
    Cleanup,
    CleanupResult,
    CreateArtifact,
)
from ontology_platform.datasets.contracts import DatasetPreview, DatasetVersionView, InitiateDataset
from ontology_platform.datasets.service import DatasetService
from ontology_platform.projects.contracts import ResourceView
from ontology_platform.projects.routes import Actor, Limit, Offset

router = APIRouter(prefix="/api/v1", tags=["datasets"])


def service(request: Request) -> DatasetService:
    return DatasetService(
        request.app.state.sessions,
        request.app.state.authorizer,
        request.app.state.artifact_settings,
        request.app.state.artifact_store,
    )


Service = Annotated[DatasetService, Depends(service)]


@router.post("/projects/{project_id}/datasets", response_model=ResourceView, status_code=201)
def create(project_id: UUID, body: CreateArtifact, actor: Actor, svc: Service) -> ResourceView:
    return svc.create(actor, project_id, body)


@router.get("/datasets/{dataset_id}", response_model=ResourceView)
def get(dataset_id: UUID, actor: Actor, svc: Service) -> ResourceView:
    with svc.scope(actor) as session:
        return ResourceView.model_validate(svc.artifact(session, actor, dataset_id))


@router.post("/datasets/{dataset_id}/uploads", response_model=DatasetVersionView, status_code=201)
def initiate(
    dataset_id: UUID, body: InitiateDataset, actor: Actor, svc: Service
) -> DatasetVersionView:
    return svc.initiate_dataset(actor, dataset_id, body)


@router.put(
    "/datasets/{dataset_id}/versions/{version_id}/content",
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
    dataset_id: UUID, version_id: UUID, request: Request, actor: Actor, svc: Service
) -> ArtifactVersionView:
    return await transport.upload(dataset_id, version_id, request, actor, svc)


@router.get("/datasets/{dataset_id}/versions/{version_id}/content")
def download(dataset_id: UUID, version_id: UUID, actor: Actor, svc: Service) -> StreamingResponse:
    return transport.download(dataset_id, version_id, actor, svc)


@router.post(
    "/datasets/{dataset_id}/versions/{version_id}/finalize", response_model=DatasetVersionView
)
def finalize(dataset_id: UUID, version_id: UUID, actor: Actor, svc: Service) -> DatasetVersionView:
    return svc.finalize_dataset(actor, dataset_id, version_id)


@router.get("/datasets/{dataset_id}/versions", response_model=list[DatasetVersionView])
def versions(
    dataset_id: UUID, actor: Actor, svc: Service, limit: Limit = 50, offset: Offset = 0
) -> list[DatasetVersionView]:
    return svc.dataset_versions(actor, dataset_id, limit, offset)


@router.get("/datasets/{dataset_id}/versions/{version_id}", response_model=DatasetVersionView)
def metadata(dataset_id: UUID, version_id: UUID, actor: Actor, svc: Service) -> DatasetVersionView:
    return svc.dataset_metadata(actor, dataset_id, version_id)


@router.get("/datasets/{dataset_id}/versions/{version_id}/preview", response_model=DatasetPreview)
def preview(
    dataset_id: UUID,
    version_id: UUID,
    actor: Actor,
    svc: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> DatasetPreview:
    return svc.preview(actor, dataset_id, version_id, limit)


@router.get("/datasets/{dataset_id}/versions/{version_id}/schema")
def schema(
    dataset_id: UUID, version_id: UUID, actor: Actor, svc: Service
) -> list[dict[str, JsonValue]]:
    return svc.preview(actor, dataset_id, version_id, 1).columns


@router.post("/datasets/{dataset_id}/cleanup", response_model=list[CleanupResult])
def cleanup(dataset_id: UUID, body: Cleanup, actor: Actor, svc: Service) -> list[CleanupResult]:
    return svc.cleanup(actor, dataset_id, body.dry_run)
