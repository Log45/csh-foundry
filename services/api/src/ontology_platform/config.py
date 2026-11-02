import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ontology_platform.security.oidc import Provider


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FOUNDRY_", env_file=".env", extra="ignore", env_ignore_empty=True
    )
    database_url: SecretStr
    database_schema: str = Field(default="public", pattern=r"^[a-z][a-z0-9_]{0,62}$")
    auth_mode: Literal["disabled", "local", "test", "oidc"] = "disabled"
    oidc_providers: tuple[Provider, ...] = ()
    oidc_ca_bundle: Path | None = None
    test_issuer: str | None = None
    test_subject: str | None = None
    worker_access_token: SecretStr | None = None
    worker_client_secret: SecretStr | None = None
    worker_provider_id: str | None = None
    worker_client_id: str = "worker"
    process_role: Literal["api", "worker"] = "api"
    worker_tenant_id: UUID | None = None
    worker_subject_id: str | None = None
    local_tenant_id: UUID | None = None
    local_principal_id: str | None = None
    trusted_local_identity: bool = False
    query_cursor_secret: SecretStr | None = None
    ingestion_catalog_json: SecretStr | None = None
    environment: Literal["development", "production"] = "development"
    public_origin: str | None = None
    allowed_hosts: tuple[str, ...] = ()
    browser_state_secret: SecretStr | None = None
    browser_state_keys: SecretStr | None = None
    browser_state_capacity: int = 1000
    request_limit_per_minute: int = 120
    tenant_storage_limit_bytes: int = 268435456
    tenant_pending_job_limit: int = 20
    database_pool_size: int = 5
    database_pool_overflow: int = 5

    @model_validator(mode="after")
    def local_context(self) -> "Settings":
        if not 1 <= self.browser_state_capacity <= 100000:
            raise ValueError("Invalid browser state capacity")
        if not 1 <= self.request_limit_per_minute <= 100000:
            raise ValueError("Invalid request limit")
        if not 1 <= self.tenant_pending_job_limit <= 1000:
            raise ValueError("Invalid job admission limit")
        if not 1048576 <= self.tenant_storage_limit_bytes <= 1099511627776:
            raise ValueError("Invalid tenant artifact quota")
        if not 1 <= self.database_pool_size <= 50 or not 0 <= self.database_pool_overflow <= 50:
            raise ValueError("Invalid database pool bounds")
        if bool(self.browser_state_secret) != bool(self.browser_state_keys):
            raise ValueError("Browser state requires both transport secret and encryption keys")
        if self.browser_state_secret and len(self.browser_state_secret.get_secret_value()) < 43:
            raise ValueError("Browser state transport secret requires at least 43 characters")
        if self.environment == "production":
            origin = urlsplit(self.public_origin or "")
            if (
                origin.scheme != "https"
                or not origin.hostname
                or origin.port not in (None, 443)
                or origin.username
                or origin.password
                or origin.query
                or origin.fragment
                or origin.path not in ("", "/")
                or origin.hostname in {"localhost", "127.0.0.1", "::1"}
            ):
                raise ValueError("Production requires an explicit public HTTPS origin")
            if self.auth_mode != "oidc" or self.trusted_local_identity:
                raise ValueError("Production requires OIDC authentication")
            if not self.allowed_hosts or any("*" in host for host in self.allowed_hosts):
                raise ValueError("Production requires explicit allowed hosts")
            if self.process_role == "api" and (
                not self.query_cursor_secret or not self.browser_state_keys
            ):
                raise ValueError("Production requires persistent cursor and session keys")
            database = urlsplit(self.database_url.get_secret_value())
            if not database.username or not database.password or not database.hostname:
                raise ValueError("Production requires explicit database credentials")
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
    return Settings(_secrets_dir=os.environ.get("FOUNDRY_SECRETS_DIRECTORY"))
