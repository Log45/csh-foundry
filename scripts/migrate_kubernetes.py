"""Serialize migrations in a separate process using the configured DDL owner account."""

from alembic import command
from alembic.config import Config
from ontology_platform.config import get_settings
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url.get_secret_value(), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            connection.execute(
                text("SELECT set_config('search_path', :schema, false)"),
                {"schema": settings.database_schema},
            )
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
