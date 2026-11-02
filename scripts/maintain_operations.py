"""Bounded session/request-budget cleanup; never removes immutable domain or audit history."""

from ontology_platform.config import get_settings
from ontology_platform.db.session import make_engine
from sqlalchemy import text

engine = make_engine(get_settings())
try:
    with engine.begin() as connection:
        for statement in (
            "DELETE FROM browser_state WHERE (kind,key) IN "
            "(SELECT kind,key FROM browser_state WHERE expires_at <= now() LIMIT 10000)",
            "DELETE FROM request_budgets WHERE key IN "
            "(SELECT key FROM request_budgets WHERE window_minute < "
            "floor(extract(epoch FROM now())/60)-60 LIMIT 10000)",
        ):
            connection.execute(text(statement))
    print("PASS bounded expired browser/request state cleanup")
finally:
    engine.dispose()
