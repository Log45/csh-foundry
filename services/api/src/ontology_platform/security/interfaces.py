from typing import Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)
    tenant_id: UUID
    principal_id: str = Field(min_length=1)
    identity_provider: str | None = None
    external_subject: str | None = None
    authentication_method: Literal["local", "oidc", "test", "delegated"] = "local"
    principal_type: Literal["user", "service"] = "user"
    expires_at: AwareDatetime | None = None
    actor_id: str | None = None
    delegation_ontology: str | None = None
    delegation_kind: Literal["ingestion", "semantic"] | None = None


class Authenticator(Protocol):
    def authenticate(self, credential: str) -> Principal: ...


class Authorizer(Protocol):
    def require(self, principal: Principal, operation: str, resource: str) -> None: ...
