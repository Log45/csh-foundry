from functools import lru_cache
from typing import Literal
from uuid import UUID

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ontology_platform.security.oidc import Provider


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FOUNDRY_", env_file=".env", extra="ignore", env_ignore_empty=True
    )
    database_url: SecretStr
    auth_mode: Literal["disabled", "local", "test", "oidc"] = "disabled"
    oidc_providers: tuple[Provider, ...] = ()
    test_issuer: str | None = None
    test_subject: str | None = None
    worker_access_token: SecretStr | None = None
    worker_tenant_id: UUID | None = None
    worker_subject_id: str | None = None
    local_tenant_id: UUID | None = None
    local_principal_id: str | None = None
    trusted_local_identity: bool = False
    query_cursor_secret: SecretStr | None = None
    ingestion_catalog_json: SecretStr | None = None

    @model_validator(mode="after")
    def local_context(self) -> "Settings":
        if self.auth_mode == "oidc":
            if self.trusted_local_identity or not self.oidc_providers:
                raise ValueError("OIDC mode requires trusted providers and forbids local identity")
            if self.test_issuer or self.test_subject:
                raise ValueError("Test identity is forbidden in OIDC mode")
        if (
            len(self.oidc_providers) > 8
            or len({p.id for p in self.oidc_providers}) != len(self.oidc_providers)
            or len({p.issuer for p in self.oidc_providers}) != len(self.oidc_providers)
        ):
            raise ValueError("Duplicate or excessive OIDC providers")
        if self.auth_mode == "test" and not (self.test_issuer and self.test_subject):
            raise ValueError("Explicit deterministic test identity required")
        if self.auth_mode == "local" and not self.trusted_local_identity:
            raise ValueError("Local mode requires explicit insecure local identity opt-in")
        if self.trusted_local_identity and self.auth_mode not in {"disabled", "local"}:
            raise ValueError("Local identity cannot coexist with verified identity modes")
        if self.trusted_local_identity and not (
            self.local_tenant_id and self.local_principal_id and self.local_principal_id.strip()
        ):
            raise ValueError("Trusted local identity requires explicit tenant and principal")
        if (
            self.query_cursor_secret is not None
            and len(self.query_cursor_secret.get_secret_value().encode()) < 32
        ):
            raise ValueError("Cursor signing secret requires at least 32 UTF-8 bytes")
        if not self.database_url.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError("Use a PostgreSQL psycopg SQLAlchemy URL")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
