from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)
    tenant_id: UUID
    principal_id: str = Field(min_length=1)


class Authenticator(Protocol):
    def authenticate(self, credential: str) -> Principal: ...


class Authorizer(Protocol):
    def require(self, principal: Principal, operation: str, resource: str) -> None: ...
