"""Authorized bounded synchronous generation; immutable artifacts remain in PostgreSQL."""

import base64
import hashlib
import json
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import Field, JsonValue
from sqlalchemy import func, select

from ontology_platform.branching.merge import changes
from ontology_platform.branching.service import page
from ontology_platform.contracts import APIModel, Compatibility
from ontology_platform.db.governance import GovernedService, missing
from ontology_platform.db.models import SDKArtifact
from ontology_platform.errors import ApplicationError
from ontology_platform.metadata.compatibility import compare
from ontology_platform.metadata.storage import definition_of, version_row
from ontology_platform.sdk.generator import Generated, Language, generate, symbols
from ontology_platform.security.interfaces import Principal


class GenerateInput(APIModel):
    version: str
    language: Language


class ArtifactView(APIModel):
    id: UUID
    schema_version: str
    language: str
    content_hash: str
    manifest: dict[str, JsonValue]
    created_by: str
    created_at: datetime
    status: str = "COMPLETED"


class Download(APIModel):
    filename: str
    media_type: str = "application/zip"
    archive_base64: str
    sha256: str


class CompatibilityInput(APIModel):
    previous_version: str
    version: str


class SDKCompatibility(APIModel):
    compatibility: Compatibility
    affected_symbols: dict[str, str]
    recommendation: str
    migration_required: bool
    diagnostics: list[str] = Field(default_factory=list)


class SDKService(GovernedService):
    def generate(
        self, p: Principal, ontology_id: str, request: GenerateInput, api_contract: dict[str, Any]
    ) -> ArtifactView:
        # The ontology lock serializes bounded generation across API processes.
        # No external IO runs in this bounded pure compiler operation.
        with self.operation(p, "schema:read", ontology_id) as session:
            ontology = self.ontology(session, p, ontology_id, write=True)
            version = version_row(session, ontology, request.version)
            if version.status != "PUBLISHED":
                raise ApplicationError(
                    "schema_unpublished", "SDK generation requires published schema", 409
                )
            generated = generate(definition_of(version), request.language, api_contract)
            archive_hash = hashlib.sha256(generated.archive()).hexdigest()
            row = session.scalar(
                select(SDKArtifact).where(
                    SDKArtifact.tenant_id == p.tenant_id,
                    SDKArtifact.ontology_id == ontology_id,
                    SDKArtifact.content_hash == archive_hash,
                )
            )
            if row is None:
                count = session.scalar(
                    select(func.count())
                    .select_from(SDKArtifact)
                    .where(
                        SDKArtifact.tenant_id == p.tenant_id, SDKArtifact.ontology_id == ontology_id
                    )
                )
                if count is not None and count >= 100:
                    raise ApplicationError("sdk_limit", "At most 100 artifacts per ontology", 409)
                row = SDKArtifact(
                    tenant_id=p.tenant_id,
                    ontology_id=ontology_id,
                    id=uuid4(),
                    schema_version=request.version,
                    language=request.language,
                    content_hash=archive_hash,
                    manifest=generated.manifest,
                    files_json=json.dumps(generated.files, sort_keys=True),
                    created_by=p.principal_id,
                )
                session.add(row)
                session.flush()
            self.authorizer.require(p, "schema:read", f"{p.tenant_id}/{ontology_id}")
            return ArtifactView.model_validate(row)

    def list_artifacts(
        self, p: Principal, ontology: str, limit: int = 50, offset: int = 0
    ) -> list[ArtifactView]:
        page(limit, offset)
        with self.operation(p, "schema:read", ontology) as session:
            self.ontology(session, p, ontology)
            return [
                ArtifactView.model_validate(row)
                for row in session.scalars(
                    select(SDKArtifact)
                    .where(
                        SDKArtifact.tenant_id == p.tenant_id, SDKArtifact.ontology_id == ontology
                    )
                    .order_by(SDKArtifact.created_at.desc(), SDKArtifact.id)
                    .limit(limit)
                    .offset(offset)
                )
            ]

    def artifact(
        self, p: Principal, ontology: str, artifact: UUID, *, download: bool = False
    ) -> ArtifactView | Download:
        with self.operation(p, "schema:read", ontology) as session:
            self.ontology(session, p, ontology)
            row = session.get(SDKArtifact, (p.tenant_id, ontology, artifact))
            if row is None:
                raise missing("SDK artifact")
            if not download:
                return ArtifactView.model_validate(row)
            generated = Generated(json.loads(row.files_json), cast(dict[str, Any], row.manifest))
            archive = generated.archive()
            if hashlib.sha256(archive).hexdigest() != row.content_hash:
                raise ApplicationError("artifact_corrupt", "Artifact hash mismatch", 409)
            return Download(
                filename=f"ontology-{row.language}-{row.schema_version}.zip",
                archive_base64=base64.b64encode(archive).decode(),
                sha256=row.content_hash,
            )

    def compatibility(
        self, p: Principal, ontology_id: str, request: CompatibilityInput
    ) -> SDKCompatibility:
        with self.operation(p, "schema:read", ontology_id) as session:
            ontology = self.ontology(session, p, ontology_id)
            previous = version_row(session, ontology, request.previous_version)
            current = version_row(session, ontology, request.version)
            if previous.status != "PUBLISHED" or current.status != "PUBLISHED":
                raise ApplicationError("schema_unpublished", "Select two published versions", 409)
            old, new = definition_of(previous), definition_of(current)
            compatibility = compare(old, new)
            old_aliases = symbols(
                sorted(
                    {o.id for o in old.object_types}
                    | {a.id for a in old.action_types}
                    | {o.id for o in new.object_types}
                    | {a.id for a in new.action_types}
                )
            )
            aliases: dict[str, str] = {}
            for change in changes(old, new):
                parts = [
                    v.replace("~1", "/").replace("~0", "~") for v in change.path.split("/")[1:]
                ]
                if len(parts) < 2:
                    continue
                group, identifier = parts[:2]
                if group == "object_types":
                    aliases["object:" + identifier] = old_aliases[identifier] + "Repository"
                    if len(parts) >= 4 and parts[2] == "properties":
                        aliases["property:" + identifier + "." + parts[3]] = (
                            old_aliases[identifier] + "Fields." + symbols([parts[3]])[parts[3]]
                        )
                elif group == "action_types":
                    aliases["action:" + identifier] = "Actions." + old_aliases[identifier]
                elif group == "link_types":
                    for link in (*old.link_types, *new.link_types):
                        if link.id == identifier:
                            for endpoint in (link.source_type, link.target_type):
                                aliases["object:" + endpoint] = old_aliases[endpoint] + "Repository"
            return SDKCompatibility(
                compatibility=compatibility,
                affected_symbols=aliases,
                recommendation=(
                    "Regenerate and type-check both SDKs; review constraints, actions "
                    "and active-version alignment"
                ),
                migration_required=compatibility.classification == "breaking",
                diagnostics=[
                    "Read properties may be omitted by server authorization and projection",
                    "Optional server additions can change client source/type compatibility",
                ],
            )
