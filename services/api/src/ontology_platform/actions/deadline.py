"""Apply a diminishing PostgreSQL statement budget to every action SQL statement."""

import time
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.engine import Connection, ExecutionContext
from sqlalchemy.engine.interfaces import DBAPICursor
from sqlalchemy.orm import Session

from ontology_platform.errors import ApplicationError


@contextmanager
def action_deadline(
    session: Session,
    expires: float,
    *,
    code: str = "action_timeout",
    message: str = "Action exceeded its 3 second budget",
) -> Iterator[None]:
    connection = session.connection()

    def before_statement(
        conn: Connection,
        cursor: DBAPICursor,
        statement: str,
        parameters: object,
        context: ExecutionContext | None,
        executemany: bool,
    ) -> None:
        # Recovery must run even after an error/expiry; SET would fail in an aborted savepoint.
        if statement.startswith(("ROLLBACK TO SAVEPOINT", "RELEASE SAVEPOINT", "SAVEPOINT")):
            return
        remaining = expires - time.monotonic()
        if remaining <= 0:
            raise ApplicationError(code, message, 503)
        # A raw cursor avoids recursively invoking SQLAlchemy's statement event.
        cursor.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(max(1, int(remaining * 1000))),),
        )

    event.listen(connection, "before_cursor_execute", before_statement)
    try:
        yield
    finally:
        event.remove(connection, "before_cursor_execute", before_statement)
