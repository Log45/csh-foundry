from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.config import Settings
from ontology_platform.errors import ApplicationError


def make_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        hide_parameters=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_overflow,
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


def require_runtime_role(sessions: sessionmaker[Session]) -> None:
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
        if privileged or owner:
            raise ApplicationError(
                "runtime_role_unsafe", "Use a non-owner runtime database role", 503
            )


@contextmanager
def transaction(factory: sessionmaker[Session]) -> Iterator[Session]:
    """One governed service operation owns one transaction; exceptions roll back."""
    with factory.begin() as session:
        yield session
