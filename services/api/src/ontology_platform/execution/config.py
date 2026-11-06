"""Independent, administrator-controlled resource budgets."""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExecutionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FOUNDRY_EXECUTION_", extra="ignore")
    retained_nodes: int = Field(default=100_000, ge=100, le=1_000_000)
    manifest_bytes: int = Field(default=16 * 1024**2, ge=1024, le=32 * 1024**2)
    dag_nodes: int = Field(default=100, ge=1, le=100)
    dag_outputs: int = Field(default=16, ge=1, le=16)
    intermediate_bytes: int = Field(default=2 * 1024**3, ge=1, le=4 * 1024**3)
    staged_bytes: int = Field(default=2 * 1024**3, ge=1, le=4 * 1024**3)
    cumulative_output_rows: int = Field(default=100_000_000, ge=1, le=100_000_000)
    node_seconds: int = Field(default=600, ge=1, le=1800)
    source_bytes: int = Field(default=1024**3, ge=1, le=1024**3)
    decoded_bytes: int = Field(default=16 * 1024**3, ge=1)
    batch_bytes: int = Field(default=8 * 1024**2, ge=65536)
    record_bytes: int = Field(default=1024**2, ge=65536)
    row_group_bytes: int = Field(default=256 * 1024**2, ge=65536)
    rows: int = Field(default=100_000_000, ge=1)
    columns: int = Field(default=256, ge=1, le=256)
    memory_bytes: int = Field(default=2 * 1024**3, ge=128 * 1024**2)
    address_bytes: int = Field(default=8 * 1024**3, ge=512 * 1024**2)
    temporary_bytes: int = Field(default=4 * 1024**3, ge=1)
    wall_seconds: int = Field(default=1800, ge=1)
    cpu_seconds: int = Field(default=1200, ge=1)
    concurrent_jobs: int = Field(default=2, ge=1, le=32)
    tenant_jobs: int = Field(default=2, ge=1)
    project_jobs: int = Field(default=1, ge=1)
    queue_jobs: int = Field(default=100, ge=1, le=10000)
    lease_seconds: int = Field(default=60, ge=10, le=600)
    attempts: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def enough_disk(self) -> "ExecutionSettings":
        if self.batch_bytes > self.memory_bytes or self.record_bytes > self.batch_bytes:
            raise ValueError("Record and batch budgets must fit worker memory")
        return self
