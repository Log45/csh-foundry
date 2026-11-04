"""Operator-only configuration; never accepted in an artifact request."""

import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FOUNDRY_ARTIFACT_",
        env_file=".env",
        extra="ignore",
        env_ignore_empty=True,
        hide_input_in_errors=True,
    )
    backend: Literal["disabled", "s3"] = "disabled"
    endpoint: str | None = None
    region: str = "us-east-1"
    bucket: str = "foundry-artifacts"
    addressing: Literal["path", "virtual"] = "path"
    access_key: SecretStr | None = None
    secret_key: SecretStr | None = None
    ca_bundle: Path | None = None
    development_http: bool = False
    client_reachable: bool = False
    presign_seconds: int = Field(default=60, ge=1, le=300)
    max_bytes: int = Field(default=1073741824, ge=1, le=1073741824)
    concurrent_uploads: int = Field(default=2, ge=1, le=32)
    tenant_uploads: int = Field(default=1, ge=1, le=32)
    transfer_seconds: int = Field(default=1800, ge=60, le=7200)
    part_bytes: int = Field(default=8388608, ge=5242880, le=67108864)
    connect_seconds: int = Field(default=3, ge=1, le=10)
    read_seconds: int = Field(default=10, ge=1, le=30)
    attempts: int = Field(default=3, ge=1, le=5)
    abandoned_seconds: int = Field(default=86400, ge=3600, le=2592000)

    @model_validator(mode="after")
    def validate_storage(self) -> "StorageSettings":
        if self.backend == "disabled":
            return self
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", self.bucket):
            raise ValueError("Invalid artifact bucket")
        if bool(self.access_key) != bool(self.secret_key):
            raise ValueError("Both S3 credentials are required, or use the SDK credential chain")
        if self.ca_bundle and not self.ca_bundle.is_file():
            raise ValueError("S3 CA bundle does not exist")
        if self.endpoint:
            url = urlsplit(self.endpoint)
            if (
                not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
                or url.path not in ("", "/")
                or url.scheme not in ({"http", "https"} if self.development_http else {"https"})
            ):
                raise ValueError("S3 endpoint must be an explicit trusted origin with verified TLS")
        elif self.development_http:
            raise ValueError("Development HTTP requires an explicit endpoint")
        if self.client_reachable and self.development_http:
            raise ValueError("Presigned capabilities require HTTPS")
        return self
