from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from ontology_platform.branching.contracts import (
    BranchCreate,
    BranchEdit,
    BranchView,
    ComparisonInput,
    ComparisonView,
    DraftHandoff,
    ExpectedRevision,
    MergeInput,
    MergePreview,
    MergeView,
    RevisionView,
)
from ontology_platform.branching.service import BranchService
from ontology_platform.contracts import VersionView
from ontology_platform.dependencies import get_principal
from ontology_platform.security.interfaces import Principal

router = APIRouter(prefix="/api/v1/ontologies/{ontology_id}", tags=["branches"])
Actor = Annotated[Principal, Depends(get_principal)]


def service(request: Request) -> BranchService:
    return BranchService(request.app.state.sessions, request.app.state.authorizer)


Branches = Annotated[BranchService, Depends(service)]


@router.post("/branches", response_model=BranchView, status_code=201)
def create(ontology_id: str, body: BranchCreate, actor: Actor, branches: Branches) -> BranchView:
    return branches.create(actor, ontology_id, body)


@router.get("/branches", response_model=list[BranchView])
def listing(
    ontology_id: str, actor: Actor, branches: Branches, limit: int = 50, offset: int = 0
) -> list[BranchView]:
    return branches.list_branches(actor, ontology_id, limit, offset)


@router.get("/branches/{branch_id}", response_model=BranchView)
def get(ontology_id: str, branch_id: UUID, actor: Actor, branches: Branches) -> BranchView:
    return branches.get(actor, ontology_id, branch_id)


@router.get("/branches/{branch_id}/head", response_model=RevisionView)
def head(ontology_id: str, branch_id: UUID, actor: Actor, branches: Branches) -> RevisionView:
    return branches.head(actor, ontology_id, branch_id)


@router.get("/branches/{branch_id}/revisions", response_model=list[RevisionView])
def history(
    ontology_id: str,
    branch_id: UUID,
    actor: Actor,
    branches: Branches,
    limit: int = 50,
    offset: int = 0,
) -> list[RevisionView]:
    return branches.history(actor, ontology_id, branch_id, limit, offset)


@router.post("/branches/{branch_id}/edit", response_model=BranchView)
def edit(
    ontology_id: str, branch_id: UUID, body: BranchEdit, actor: Actor, branches: Branches
) -> BranchView:
    return branches.edit(actor, ontology_id, branch_id, body)


@router.post("/branches/{branch_id}/abandon", response_model=BranchView)
def abandon(
    ontology_id: str, branch_id: UUID, body: ExpectedRevision, actor: Actor, branches: Branches
) -> BranchView:
    return branches.abandon(actor, ontology_id, branch_id, body.expected_revision)


@router.post("/branches/{branch_id}/compare", response_model=ComparisonView)
def comparison(
    ontology_id: str, branch_id: UUID, body: ComparisonInput, actor: Actor, branches: Branches
) -> ComparisonView:
    return branches.comparison(actor, ontology_id, branch_id, body)


@router.post("/branches/{branch_id}/merge-preview", response_model=MergePreview)
def preview(
    ontology_id: str, branch_id: UUID, body: MergeInput, actor: Actor, branches: Branches
) -> MergePreview:
    return branches.preview(actor, ontology_id, branch_id, body)


@router.post("/branches/{branch_id}/merge", response_model=MergeView)
def merge(
    ontology_id: str, branch_id: UUID, body: MergeInput, actor: Actor, branches: Branches
) -> MergeView:
    return branches.merge(actor, ontology_id, branch_id, body)


@router.post("/branches/{branch_id}/draft", response_model=VersionView, status_code=201)
def draft(
    ontology_id: str, branch_id: UUID, body: DraftHandoff, actor: Actor, branches: Branches
) -> VersionView:
    return branches.draft(actor, ontology_id, branch_id, body)


@router.get("/merges", response_model=list[MergeView])
def merges(
    ontology_id: str, actor: Actor, branches: Branches, limit: int = 50, offset: int = 0
) -> list[MergeView]:
    return branches.merges(actor, ontology_id, limit, offset)
