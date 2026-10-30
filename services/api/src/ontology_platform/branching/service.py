"""Canonical branching under the registry's existing transaction/security/ontology locks."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from ontology_schema.models import OntologyDefinition
from pydantic import JsonValue, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ontology_platform.branching.contracts import (
    BranchCreate,
    BranchEdit,
    BranchView,
    ComparisonInput,
    ComparisonView,
    DraftHandoff,
    MergeConflict,
    MergeInput,
    MergePreview,
    MergeView,
    RevisionView,
)
from ontology_platform.branching.merge import changes, three_way
from ontology_platform.contracts import VersionView
from ontology_platform.db.governance import GovernedService, missing
from ontology_platform.db.models import BranchMerge, BranchRevision, Ontology, SchemaBranch
from ontology_platform.errors import ApplicationError
from ontology_platform.metadata.compatibility import compare
from ontology_platform.metadata.service import RegistryService
from ontology_platform.metadata.storage import active_definition, definition_of, digest, version_row
from ontology_platform.security.interfaces import Principal


def hash_payload(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def bounded(definition: OntologyDefinition) -> None:
    if len(definition.canonical_json().encode()) > 65536:
        raise ApplicationError("schema_too_large", "Branch schema exceeds 64 KiB", 422)


def page(limit: int, offset: int) -> None:
    if not 1 <= limit <= 100 or not 0 <= offset <= 10000:
        raise ApplicationError("invalid_page", "Invalid page bounds", 422)


def revision_view(row: BranchRevision) -> RevisionView:
    return RevisionView(
        branch_id=row.branch_id,
        revision=row.revision,
        parent_revision=row.parent_revision,
        content_hash=row.content_hash,
        definition=OntologyDefinition.model_validate_json(row.definition_json),
        author=row.author,
        summary=row.summary,
        provenance=row.provenance,
        created_at=row.created_at,
    )


class BranchService(GovernedService):
    @staticmethod
    def branch(
        session: Session,
        p: Principal,
        ontology: str,
        branch_id: UUID,
        *,
        expected: int | None = None,
        active: bool = False,
    ) -> SchemaBranch:
        row = session.get(SchemaBranch, (p.tenant_id, ontology, branch_id))
        if row is None:
            raise missing("Branch")
        if active and row.state != "ACTIVE":
            raise ApplicationError("branch_closed", "Branch is merged or abandoned", 409)
        if expected is not None and row.head_revision != expected:
            raise ApplicationError("branch_changed", "Branch revision changed; reload", 412)
        return row

    @staticmethod
    def snapshot(
        session: Session, row: SchemaBranch, revision: int | None = None
    ) -> BranchRevision:
        found = session.get(
            BranchRevision, (row.tenant_id, row.ontology_id, row.id, revision or row.head_revision)
        )
        if found is None:
            raise missing("Branch revision")
        return found

    @staticmethod
    def append(
        session: Session,
        row: SchemaBranch,
        definition: OntologyDefinition,
        principal: Principal,
        summary: str,
        provenance: dict[str, JsonValue],
        *,
        initial: bool = False,
    ) -> None:
        bounded(definition)
        previous = None if initial else row.head_revision
        row.head_revision = 1 if initial else row.head_revision + 1
        row.head_hash = digest(definition)
        row.updated_at, row.updated_by = datetime.now(UTC), principal.principal_id
        session.add(
            BranchRevision(
                tenant_id=row.tenant_id,
                ontology_id=row.ontology_id,
                branch_id=row.id,
                revision=row.head_revision,
                parent_revision=previous,
                content_hash=row.head_hash,
                definition_json=definition.canonical_json(),
                author=principal.principal_id,
                summary=summary,
                provenance=provenance,
            )
        )
        session.flush()

    def create(self, p: Principal, ontology_id: str, request: BranchCreate) -> BranchView:
        with self.operation(p, "schema:write", ontology_id) as session:
            ontology = self.ontology(session, p, ontology_id, write=True)
            base = request.base_version or ontology.active_version
            if base is None:
                raise ApplicationError("base_required", "Select a published base", 422)
            version = version_row(session, ontology, base)
            if version.status != "PUBLISHED":
                raise ApplicationError("schema_unpublished", "Branch base must be published", 409)
            count = session.scalar(
                select(func.count())
                .select_from(SchemaBranch)
                .where(
                    SchemaBranch.tenant_id == p.tenant_id, SchemaBranch.ontology_id == ontology_id
                )
            )
            if count is not None and count >= 100:
                raise ApplicationError("branch_limit", "At most 100 branches per ontology", 409)
            definition = definition_of(version)
            if digest(definition) != version.content_hash:
                raise ApplicationError("invalid_base", "Base content hash mismatch", 409)
            row = SchemaBranch(
                tenant_id=p.tenant_id,
                ontology_id=ontology_id,
                id=uuid4(),
                name=request.name,
                description=request.description,
                base_version=base,
                base_hash=version.content_hash,
                head_revision=1,
                head_hash=version.content_hash,
                created_by=p.principal_id,
                updated_by=p.principal_id,
            )
            session.add(row)
            session.flush()
            self.append(
                session, row, definition, p, "Branch created", {"base_version": base}, initial=True
            )
            return BranchView.model_validate(row)

    def list_branches(
        self, p: Principal, ontology: str, limit: int = 50, offset: int = 0
    ) -> list[BranchView]:
        page(limit, offset)
        with self.operation(p, "schema:read", ontology) as session:
            self.ontology(session, p, ontology)
            return [
                BranchView.model_validate(row)
                for row in session.scalars(
                    select(SchemaBranch)
                    .where(
                        SchemaBranch.tenant_id == p.tenant_id, SchemaBranch.ontology_id == ontology
                    )
                    .order_by(SchemaBranch.name, SchemaBranch.id)
                    .limit(limit)
                    .offset(offset)
                )
            ]

    def get(self, p: Principal, ontology: str, branch_id: UUID) -> BranchView:
        with self.operation(p, "schema:read", ontology) as session:
            self.ontology(session, p, ontology)
            return BranchView.model_validate(self.branch(session, p, ontology, branch_id))

    def history(
        self, p: Principal, ontology: str, branch_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[RevisionView]:
        page(limit, offset)
        with self.operation(p, "schema:read", ontology) as session:
            self.ontology(session, p, ontology)
            row = self.branch(session, p, ontology, branch_id)
            return [
                revision_view(rev)
                for rev in session.scalars(
                    select(BranchRevision)
                    .where(
                        BranchRevision.tenant_id == p.tenant_id,
                        BranchRevision.ontology_id == ontology,
                        BranchRevision.branch_id == row.id,
                    )
                    .order_by(BranchRevision.revision.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ]

    def head(self, p: Principal, ontology: str, branch_id: UUID) -> RevisionView:
        with self.operation(p, "schema:read", ontology) as session:
            self.ontology(session, p, ontology)
            return revision_view(
                self.snapshot(session, self.branch(session, p, ontology, branch_id))
            )

    def edit(
        self, p: Principal, ontology_id: str, branch_id: UUID, request: BranchEdit
    ) -> BranchView:
        with self.operation(p, "schema:write", ontology_id) as session:
            ontology = self.ontology(session, p, ontology_id, write=True)
            row = self.branch(
                session, p, ontology_id, branch_id, expected=request.expected_revision, active=True
            )
            RegistryService._identity(p, ontology, request.definition)
            if request.definition.version != row.base_version:
                raise ApplicationError(
                    "branch_version",
                    "Branch keeps base version; choose new version at draft handoff",
                    422,
                )
            self.append(session, row, request.definition, p, request.summary, {"kind": "edit"})
            self.authorizer.require(p, "schema:write", f"{p.tenant_id}/{ontology_id}")
            return BranchView.model_validate(row)

    def abandon(self, p: Principal, ontology: str, branch_id: UUID, expected: int) -> BranchView:
        with self.operation(p, "schema:write", ontology) as session:
            self.ontology(session, p, ontology, write=True)
            row = self.branch(session, p, ontology, branch_id, expected=expected, active=True)
            row.state, row.updated_by, row.updated_at = (
                "ABANDONED",
                p.principal_id,
                datetime.now(UTC),
            )
            session.flush()
            return BranchView.model_validate(row)

    def comparison(
        self, p: Principal, ontology_id: str, branch_id: UUID, request: ComparisonInput
    ) -> ComparisonView:
        with self.operation(p, "schema:read", ontology_id) as session:
            ontology = self.ontology(session, p, ontology_id)
            row = self.branch(session, p, ontology_id, branch_id)
            source = revision_view(self.snapshot(session, row, request.source_revision))
            choices = (
                int(request.target_branch is not None)
                + int(request.target_version is not None)
                + int(request.active)
            )
            if choices > 1 or (
                request.target_revision is not None and request.target_branch is None
            ):
                raise ApplicationError("invalid_comparison", "Select one comparison target", 422)
            if request.target_branch:
                target = self.branch(session, p, ontology_id, request.target_branch)
                snap = revision_view(self.snapshot(session, target, request.target_revision))
                definition, ref = snap.definition, f"{target.id}:{snap.revision}"
            elif request.active:
                definition, ref = active_definition(session, ontology), "active"
            else:
                version = version_row(session, ontology, request.target_version or row.base_version)
                if version.status != "PUBLISHED":
                    raise ApplicationError(
                        "schema_unpublished", "Comparison version must be published", 409
                    )
                definition, ref = definition_of(version), version.version
            return ComparisonView(
                source=f"{row.id}:{source.revision}",
                target=ref,
                source_hash=source.content_hash,
                target_hash=digest(definition),
                changes=changes(definition, source.definition),
                compatibility=compare(definition, source.definition),
            )

    def _preview(
        self,
        session: Session,
        p: Principal,
        ontology: Ontology,
        target_id: UUID,
        request: MergeInput,
    ) -> tuple[MergePreview, SchemaBranch, SchemaBranch]:
        target = self.branch(
            session, p, ontology.id, target_id, expected=request.target_revision, active=True
        )
        source = self.branch(
            session,
            p,
            ontology.id,
            request.source_branch,
            expected=request.source_revision,
            active=True,
        )
        if target.id == source.id:
            raise ApplicationError("invalid_merge", "Source and target must differ", 422)
        if (source.base_version, source.base_hash) != (target.base_version, target.base_hash):
            raise ApplicationError(
                "unrelated_base", "Merge requires the same immutable published base", 409
            )
        # A target with earlier merges can still accept independent sibling branches; already merged
        # sources are terminal and cannot be reused or silently rebased.
        base = definition_of(version_row(session, ontology, target.base_version))
        ours = revision_view(self.snapshot(session, target)).definition
        theirs = revision_view(self.snapshot(session, source)).definition
        schema_resolutions = [r for r in request.resolutions if r.conflict == "/$schema"]
        if len(schema_resolutions) > 1:
            raise ApplicationError("invalid_resolution", "Duplicate schema resolution", 422)
        raw, conflicts = three_way(
            base, ours, theirs, [r for r in request.resolutions if r.conflict != "/$schema"]
        )
        diagnostics: list[str] = []
        definition = None
        try:
            definition = OntologyDefinition.model_validate(raw)
            RegistryService._identity(p, ontology, definition)
            bounded(definition)
        except ValidationError as exc:
            diagnostics = [
                f"{'.'.join(str(v) for v in e['loc'])}: {e['type']}" for e in exc.errors()[:64]
            ]
        if diagnostics:
            resolution = schema_resolutions[0] if schema_resolutions else None
            conflicts.append(
                MergeConflict(
                    id="/$schema",
                    category="canonical_validation",
                    base=base.model_dump(mode="json"),
                    target=ours.model_dump(mode="json"),
                    source=theirs.model_dump(mode="json"),
                    base_present=True,
                    target_present=True,
                    source_present=True,
                    resolved=resolution is not None,
                )
            )
            if resolution is not None:
                selected = (
                    ours.model_dump(mode="json")
                    if resolution.strategy == "target"
                    else theirs.model_dump(mode="json")
                    if resolution.strategy == "source"
                    else resolution.value
                )
                try:
                    definition = OntologyDefinition.model_validate(selected)
                    RegistryService._identity(p, ontology, definition)
                    bounded(definition)
                    diagnostics = []
                except ValidationError:
                    definition = None
                    diagnostics = ["Manual schema resolution fails canonical validation"]
        elif schema_resolutions:
            raise ApplicationError(
                "invalid_resolution", "No canonical validation conflict exists", 422
            )
        compatibility = (
            compare(
                active_definition(session, ontology) if ontology.active_version else None,
                definition,
            )
            if definition
            else None
        )
        payload: dict[str, Any] = dict(
            source_branch=source.id,
            target_branch=target.id,
            source_revision=source.head_revision,
            target_revision=target.head_revision,
            source_hash=source.head_hash,
            target_hash=target.head_hash,
            base_version=source.base_version,
            base_hash=source.base_hash,
            conflicts=conflicts,
            resolutions=request.resolutions,
            definition=definition,
            diagnostics=diagnostics,
            changes=changes(ours, definition) if definition else [],
            compatibility=compatibility,
            migration_required=bool(compatibility and compatibility.classification == "breaking"),
        )
        preview = MergePreview(preview_hash="pending", **payload)
        preview.preview_hash = hash_payload(
            preview.model_dump(mode="json", exclude={"preview_hash"})
        )
        return preview, target, source

    def preview(
        self, p: Principal, ontology_id: str, target: UUID, request: MergeInput
    ) -> MergePreview:
        with self.operation(p, "schema:read", ontology_id) as session:
            ontology = self.ontology(session, p, ontology_id)
            return self._preview(session, p, ontology, target, request)[0]

    def merge(
        self, p: Principal, ontology_id: str, target_id: UUID, request: MergeInput
    ) -> MergeView:
        with self.operation(p, "schema:write", ontology_id) as session:
            ontology = self.ontology(session, p, ontology_id, write=True)
            preview, target, source = self._preview(session, p, ontology, target_id, request)
            if request.preview_hash != preview.preview_hash:
                raise ApplicationError(
                    "stale_preview", "Generate a fresh resolved merge preview", 412
                )
            if preview.definition is None or any(not c.resolved for c in preview.conflicts):
                raise ApplicationError(
                    "merge_conflicts", "Resolve conflicts and canonical diagnostics first", 409
                )
            merge_id = uuid4()
            provenance: dict[str, JsonValue] = {
                "base_version": preview.base_version,
                "base_hash": preview.base_hash,
                "source_hash": preview.source_hash,
                "target_hash": preview.target_hash,
                "result_hash": digest(preview.definition),
                "preview_hash": preview.preview_hash,
                "resolutions": [r.model_dump(mode="json") for r in request.resolutions],
                "outcome": "MERGED",
            }
            self.append(
                session,
                target,
                preview.definition,
                p,
                "Merge " + str(source.id),
                {"merge_id": str(merge_id)},
            )
            record = BranchMerge(
                tenant_id=p.tenant_id,
                ontology_id=ontology_id,
                id=merge_id,
                source_id=source.id,
                source_revision=request.source_revision,
                target_id=target.id,
                target_revision=request.target_revision,
                result_revision=target.head_revision,
                provenance=provenance,
                author=p.principal_id,
            )
            session.add(record)
            source.state, source.updated_by, source.updated_at = (
                "MERGED",
                p.principal_id,
                datetime.now(UTC),
            )
            self.authorizer.require(p, "schema:write", f"{p.tenant_id}/{ontology_id}")
            session.flush()
            return MergeView.model_validate(record)

    def merges(
        self, p: Principal, ontology: str, limit: int = 50, offset: int = 0
    ) -> list[MergeView]:
        page(limit, offset)
        with self.operation(p, "schema:read", ontology) as session:
            self.ontology(session, p, ontology)
            return [
                MergeView.model_validate(row)
                for row in session.scalars(
                    select(BranchMerge)
                    .where(
                        BranchMerge.tenant_id == p.tenant_id, BranchMerge.ontology_id == ontology
                    )
                    .order_by(BranchMerge.created_at.desc(), BranchMerge.id)
                    .limit(limit)
                    .offset(offset)
                )
            ]

    def draft(
        self, p: Principal, ontology_id: str, branch_id: UUID, request: DraftHandoff
    ) -> VersionView:
        with self.operation(p, "schema:write", ontology_id) as session:
            self.ontology(session, p, ontology_id, write=True)
            row = self.branch(
                session, p, ontology_id, branch_id, expected=request.expected_revision
            )
            if row.state == "ABANDONED":
                raise ApplicationError("branch_closed", "Cannot hand off abandoned branch", 409)
            data = revision_view(self.snapshot(session, row)).definition.model_dump(mode="json")
            data["version"] = request.version
            return RegistryService(self.sessions, self.authorizer, session=session).draft(
                p, ontology_id, OntologyDefinition.model_validate(data)
            )
