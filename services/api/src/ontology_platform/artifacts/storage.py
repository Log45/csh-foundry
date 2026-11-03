"""Provider-neutral, opaque and immutable object storage contract."""

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import BinaryIO, Protocol
from uuid import UUID

from ontology_platform.errors import ApplicationError


class Failure(StrEnum):
    MISSING = "missing"
    ACCESS = "access"
    INTEGRITY = "integrity"
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    CONFIGURATION = "configuration"
    EXISTS = "exists"


class StorageError(ApplicationError):
    def __init__(self, category: Failure):
        self.category = category
        super().__init__(
            f"storage_{category}",
            f"Artifact storage {category}",
            409 if category in {Failure.INTEGRITY, Failure.EXISTS} else 503,
        )


@dataclass(frozen=True)
class ObjectKey:
    tenant: UUID
    artifact: UUID
    version: UUID

    def __post_init__(self) -> None:
        if not all(isinstance(v, UUID) for v in (self.tenant, self.artifact, self.version)):
            raise StorageError(Failure.CONFIGURATION)

    def __str__(self) -> str:
        return f"v1/{self.tenant}/{self.artifact}/{self.version}"


@dataclass(frozen=True)
class ObjectInfo:
    size: int
    sha256: str | None = None


class ArtifactStore(Protocol):
    backend: str

    def put(self, key: ObjectKey, source: BinaryIO, size: int, checksum: str) -> None: ...
    def chunks(self, key: ObjectKey) -> Iterator[bytes]: ...
    def head(self, key: ObjectKey) -> ObjectInfo: ...
    def exists(self, key: ObjectKey) -> bool: ...
    def verify(self, key: ObjectKey, size: int, checksum: str) -> ObjectInfo: ...
    def delete(self, key: ObjectKey) -> None: ...
    def presign(self, key: ObjectKey) -> str: ...
    def abort_pending(self, key: ObjectKey) -> None: ...
