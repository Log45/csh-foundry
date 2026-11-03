"""Opt-in bounded request timings; never retain statements, parameters or identities."""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import Engine, event
from sqlalchemy.pool import QueuePool

current: ContextVar[dict[str, float] | None] = ContextVar("request_timings", default=None)


@contextmanager
def stage(name: str) -> Iterator[None]:
    values = current.get()
    if values is None:
        yield
        return
    started = time.monotonic()
    try:
        yield
    finally:
        values[name] = values.get(name, 0.0) + time.monotonic() - started


class DiagnosticPool(QueuePool):
    """Includes queue wait, connection creation, pre-ping and checkout listeners."""

    diagnostic_role = "ordinary"

    def connect(self) -> Any:
        with stage(self.diagnostic_role + "_acquire_seconds"):
            return super().connect()


def instrument(engine: Engine, role: str) -> None:
    assert isinstance(engine.pool, DiagnosticPool)
    engine.pool.diagnostic_role = role

    @event.listens_for(engine, "before_cursor_execute")
    def before(conn: Any, *args: Any) -> None:
        conn.info["diagnostic_sql_start"] = time.monotonic()

    @event.listens_for(engine, "after_cursor_execute")
    def after(conn: Any, *args: Any) -> None:
        started = conn.info.pop("diagnostic_sql_start", None)
        values = current.get()
        if values is not None and started is not None:
            key = role + "_sql_seconds"
            values[key] = values.get(key, 0.0) + time.monotonic() - started
            key = role + "_statements"
            values[key] = values.get(key, 0.0) + 1

    @event.listens_for(engine, "handle_error")
    def failed(context: Any) -> None:
        if context.connection is not None:
            after(context.connection)
