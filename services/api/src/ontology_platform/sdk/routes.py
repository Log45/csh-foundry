from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ontology_platform.dependencies import get_principal
from ontology_platform.sdk.service import (
    ArtifactView,
    CompatibilityInput,
    Download,
    GenerateInput,
    SDKCompatibility,
    SDKService,
)
from ontology_platform.security.interfaces import Principal

router = APIRouter(prefix="/api/v1/ontologies/{ontology_id}/sdk", tags=["sdk"])
Actor = Annotated[Principal, Depends(get_principal)]


def service(request: Request) -> SDKService:
    return SDKService(request.app.state.sessions, request.app.state.authorizer)


SDK = Annotated[SDKService, Depends(service)]


@router.post("/generate", response_model=ArtifactView)
def generation(
    ontology_id: str, body: GenerateInput, actor: Actor, sdk: SDK, request: Request
) -> ArtifactView:
    return sdk.generate(actor, ontology_id, body, request.app.openapi())


@router.get("/artifacts", response_model=list[ArtifactView])
def listing(
    ontology_id: str, actor: Actor, sdk: SDK, limit: int = 50, offset: int = 0
) -> list[ArtifactView]:
    return sdk.list_artifacts(actor, ontology_id, limit, offset)


@router.get("/artifacts/{artifact_id}", response_model=ArtifactView)
def artifact(ontology_id: str, artifact_id: UUID, actor: Actor, sdk: SDK) -> ArtifactView:
    return ArtifactView.model_validate(sdk.artifact(actor, ontology_id, artifact_id))


@router.get("/artifacts/{artifact_id}/download", response_model=Download)
def download(ontology_id: str, artifact_id: UUID, actor: Actor, sdk: SDK) -> Download:
    return Download.model_validate(sdk.artifact(actor, ontology_id, artifact_id, download=True))


@router.post("/compatibility", response_model=SDKCompatibility)
def compatibility(
    ontology_id: str, body: CompatibilityInput, actor: Actor, sdk: SDK
) -> SDKCompatibility:
    return sdk.compatibility(actor, ontology_id, body)
