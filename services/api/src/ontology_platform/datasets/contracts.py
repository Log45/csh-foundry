from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue

from ontology_platform.artifacts.contracts import ArtifactVersionView, InitiateUpload
from ontology_platform.projects.contracts import Model


class InitiateDataset(InitiateUpload):
    size: int = Field(ge=0, le=8 * 1024 * 1024)
    format: Literal["csv", "json", "ndjson", "parquet"]


class DatasetVersionView(ArtifactVersionView):
    format: str
    artifact_state: str
    result: dict[str, JsonValue]
    validated_at: datetime | None


class DatasetPreview(Model):
    columns: list[dict[str, JsonValue]]
    rows: list[list[JsonValue]]
    row_count: int
