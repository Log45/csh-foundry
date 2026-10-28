from alembic import context
from ontology_platform.config import get_settings
from ontology_platform.db.models import Base
from sqlalchemy import create_engine, pool

url = get_settings().database_url.get_secret_value()
if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
