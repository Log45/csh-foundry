"""Serialize migrations using one PostgreSQL advisory-lock session, never a runtime role."""

from alembic import command
from alembic.config import Config
from ontology_platform.config import get_settings
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


def main() -> None:
    engine = create_engine(get_settings().database_url.get_secret_value(), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            acquired = connection.scalar(text("SELECT pg_try_advisory_lock(7041000017)"))
            connection.commit()
            if not acquired:
                raise RuntimeError("Another migration is running; rollout must remain stopped")
            try:
                config = Config("alembic.ini")
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
                command.check(config)
            finally:
                connection.rollback()
                connection.execute(text("SELECT pg_advisory_unlock(7041000017)"))
                connection.commit()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
