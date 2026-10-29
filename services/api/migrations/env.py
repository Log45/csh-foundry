from alembic import context
from ontology_platform.config import get_settings
from ontology_platform.db.models import Base
from sqlalchemy import create_engine, pool, text
from sqlalchemy.engine import Connection


def run(connection: Connection) -> None:
    def include_object(obj, name, type_, reflected, compare_to):
        # PostgreSQL reflects a COLLATE-only index as plain columns. Suppress that
        # false difference only when the real catalog definition matches exactly;
        # missing, changed-column, unique or wrong-collation indexes remain drift.
        if type_ == "index" and name == "ix_objects_query_order" and compare_to is not None:
            definition = connection.scalar(
                text("SELECT pg_get_indexdef(to_regclass(:name))"), {"name": name}
            )
            if (
                definition is not None
                and definition.endswith(
                    ' USING btree (tenant_id, ontology_id, object_type_id, object_id COLLATE "C")'
                )
                and "CREATE UNIQUE INDEX" not in definition
            ):
                return False
        return True

    context.configure(
        connection=connection, target_metadata=Base.metadata, include_object=include_object
    )
    with context.begin_transaction():
        context.run_migrations()


provided = context.config.attributes.get("connection")
if provided is not None:
    run(provided)
elif context.is_offline_mode():
    context.configure(
        url=get_settings().database_url.get_secret_value(),
        target_metadata=Base.metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(get_settings().database_url.get_secret_value(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        run(connection)
    engine.dispose()
