from functools import lru_cache
from uuid import UUID

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FOUNDRY_", env_file=".env", extra="ignore", env_ignore_empty=True
    )
    database_url: SecretStr
    local_tenant_id: UUID | None = None
    local_principal_id: str | None = None
    trusted_local_identity: bool = False

    @model_validator(mode="after")
    def local_context(self) -> "Settings":
        if self.trusted_local_identity and not (
            self.local_tenant_id and self.local_principal_id and self.local_principal_id.strip()
        ):
            raise ValueError("Trusted local identity requires explicit tenant and principal")
        if not self.database_url.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError("Use a PostgreSQL psycopg SQLAlchemy URL")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
