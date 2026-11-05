from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ontology_platform.artifacts.contracts import CreateArtifact
from ontology_platform.functions.contracts import GovernedDefinitionView
from ontology_platform.media.contracts import AttachMedia, ItemView, MediaSnapshotView, Snapshot
from ontology_platform.media.service import MediaService
from ontology_platform.projects.contracts import ResourceView
from ontology_platform.projects.routes import Actor, Limit, Offset

router = APIRouter(prefix="/api/v1", tags=["media-sets"])


def service(request: Request) -> MediaService:
    return MediaService(
        request.app.state.sessions,
        request.app.state.authorizer,
        request.app.state.artifact_settings,
        request.app.state.artifact_store,
    )


Service = Annotated[MediaService, Depends(service)]


@router.post("/projects/{project_id}/media-sets", response_model=ResourceView, status_code=201)
def create(project_id: UUID, body: CreateArtifact, actor: Actor, svc: Service) -> ResourceView:
    return svc.create(actor, project_id, body)


@router.get("/media-sets/{set_id}", response_model=ResourceView)
def get(set_id: UUID, actor: Actor, svc: Service) -> ResourceView:
    with svc.scope(actor) as s:
        return ResourceView.model_validate(svc.artifact(s, actor, set_id))


@router.post("/media-sets/{set_id}/validate", response_model=Snapshot)
def validate(set_id: UUID, body: Snapshot, actor: Actor, svc: Service) -> Snapshot:
    with svc.scope(actor) as s:
        svc.artifact(s, actor, set_id, True)
        for item in body.items:
            svc.item(s, actor, set_id, item)
        return body


@router.post("/media-sets/{set_id}/definitions", response_model=MediaSnapshotView, status_code=201)
def publish(set_id: UUID, body: Snapshot, actor: Actor, svc: Service) -> GovernedDefinitionView:
    return svc.publish_snapshot(actor, set_id, body)


@router.get("/media-sets/{set_id}/definitions", response_model=list[MediaSnapshotView])
def definitions(
    set_id: UUID, actor: Actor, svc: Service, limit: Limit = 50, offset: Offset = 0
) -> list[GovernedDefinitionView]:
    return svc.published_definitions(actor, set_id, limit, offset)


@router.get("/media-sets/{set_id}/definitions/{definition_id}", response_model=MediaSnapshotView)
def definition(
    set_id: UUID, definition_id: UUID, actor: Actor, svc: Service
) -> GovernedDefinitionView:
    with svc.scope(actor) as s:
        row = svc.governed_definition(s, actor, set_id, definition_id)
        result = GovernedDefinitionView.model_validate(row)
        result.specification = {
            "items": [
                str(i.id) for i in svc.snapshot_items(s, actor, set_id, definition_id, 10000, 0)
            ]
        }
        return result


@router.post("/media-sets/{set_id}/items", response_model=ItemView, status_code=201)
def attach(set_id: UUID, body: AttachMedia, actor: Actor, svc: Service) -> ItemView:
    from ontology_platform.artifacts.admission import TransferSlot

    slot = TransferSlot(
        svc.sessions, actor.tenant_id, svc.settings.concurrent_uploads, svc.settings.tenant_uploads
    )
    slot.acquire()
    try:
        return svc.attach(actor, set_id, body)
    finally:
        slot.release()


@router.get("/media-sets/{set_id}/items", response_model=list[ItemView])
def items(
    set_id: UUID,
    actor: Actor,
    svc: Service,
    limit: Limit = 50,
    offset: Offset = 0,
    version_id: UUID | None = None,
) -> list[ItemView]:
    return svc.items(actor, set_id, limit, offset, version_id)


@router.get("/media-sets/{set_id}/items/{item_id}", response_model=ItemView)
def item(set_id: UUID, item_id: UUID, actor: Actor, svc: Service) -> ItemView:
    with svc.scope(actor) as s:
        return svc.view(svc.item(s, actor, set_id, item_id))


@router.get("/media-sets/{set_id}/items/{item_id}/content")
def content(
    set_id: UUID, item_id: UUID, actor: Actor, svc: Service, preview: bool = False
) -> StreamingResponse:
    from ontology_platform.artifacts.admission import TransferSlot

    slot = TransferSlot(
        svc.sessions, actor.tenant_id, svc.settings.concurrent_uploads, svc.settings.tenant_uploads
    )
    slot.acquire()
    try:
        source, size = svc.content(actor, set_id, item_id, preview)
    except BaseException:
        slot.release()
        raise

    def chunks() -> Iterator[bytes]:
        try:
            while chunk := source.read(1024**2):
                yield chunk
        finally:
            source.close()
            slot.release()

    return StreamingResponse(
        chunks(),
        media_type="image/jpeg" if preview else "application/octet-stream",
        headers={
            "Content-Length": str(size),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "attachment; filename=media.bin",
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
        },
    )


@router.get("/media-sets/{set_id}/items/{item_id}/lineage", response_model=ItemView)
def lineage(set_id: UUID, item_id: UUID, actor: Actor, svc: Service) -> ItemView:
    with svc.scope(actor) as s:
        return svc.view(svc.item(s, actor, set_id, item_id))
