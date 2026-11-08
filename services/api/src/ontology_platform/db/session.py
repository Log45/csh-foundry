from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.config import Settings
from ontology_platform.errors import ApplicationError


def clock(session: Session) -> datetime:
    """Use the database clock for durable leases across independent worker processes."""
    value = session.scalar(select(func.clock_timestamp()))
    assert isinstance(value, datetime)
    return value


def make_engine(settings: Settings, *, audit: bool = False) -> Engine:
    from ontology_platform.diagnostics import DiagnosticPool, instrument

    engine = create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        **({"poolclass": DiagnosticPool} if settings.diagnostic_timing else {}),
        hide_parameters=True,
        # Independent audit transactions must not compete with business transactions
        # that hold all ordinary connections while waiting for the same ontology lock.
        pool_size=2 if audit else settings.database_pool_size,
        max_overflow=0 if audit else settings.database_pool_overflow,
        pool_timeout=3,
        connect_args={
            "connect_timeout": 3,
            "options": (
                "-c statement_timeout=3000 -c lock_timeout=2000 "
                "-c idle_in_transaction_session_timeout=60000 "
                f"-c search_path={settings.database_schema} "
                f"-c foundry.storage_limit={settings.tenant_storage_limit_bytes} "
                f"-c foundry.job_limit={settings.tenant_pending_job_limit}"
            ),
        },
    )
    if settings.diagnostic_timing:
        instrument(engine, "audit" if audit else "ordinary")
    return engine


def require_runtime_role(
    sessions: sessionmaker[Session], *, allow_owner_runtime_role: bool = False
) -> None:
    """Allow opted-in table ownership only; elevated role flags are never exempted."""
    with sessions() as session:
        privileged = session.scalar(
            text("""
            SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication
            FROM pg_roles WHERE rolname = current_user
        """)
        )
        owner = session.scalar(
            text("""
            SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
              WHERE n.nspname=current_schema() AND c.relkind IN ('r','p')
              AND c.relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user))
        """)
        )
        if privileged:
            raise ApplicationError(
                "runtime_role_unsafe", "Database role has elevated PostgreSQL privileges", 503
            )
        if owner and not allow_owner_runtime_role:
            raise ApplicationError(
                "runtime_role_unsafe",
                "Database table ownership requires FOUNDRY_ALLOW_OWNER_RUNTIME_ROLE=true",
                503,
            )


@contextmanager
def transaction(factory: sessionmaker[Session]) -> Iterator[Session]:
    """One governed service operation owns one transaction; exceptions roll back."""
    with factory.begin() as session:
        yield session
