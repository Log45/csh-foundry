from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.config import Settings


def make_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=3000"},
    )


@contextmanager
def transaction(factory: sessionmaker[Session]) -> Iterator[Session]:
    """One governed service operation owns one transaction; exceptions roll back."""
    with factory.begin() as session:
        yield session
