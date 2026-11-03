"""Request context survives sync execution, fails closed, and never exports SQL content."""

import asyncio
import logging

from ontology_platform.diagnostics import DiagnosticPool, current, instrument
from ontology_platform.operations import RequestTelemetry, Telemetry
from sqlalchemy import create_engine, text


def test_correlated_sql_context_isolation_and_failed_statement():
    engine = create_engine("sqlite://", poolclass=DiagnosticPool)
    instrument(engine, "ordinary")
    values = {}
    token = current.set(values)
    try:
        with engine.connect() as sql:
            sql.execute(text("SELECT 'private-payload'"))
        assert values["ordinary_acquire_seconds"] >= 0
        assert values["ordinary_sql_seconds"] >= 0
        assert values["ordinary_statements"] == 1
        assert "private" not in str(values)
    finally:
        current.reset(token)
        engine.dispose()
    assert current.get() is None


def test_request_timing_opt_in_and_thread_context(caplog):
    async def run(enabled):
        async def downstream(scope, receive, send):
            def sync_work():
                value = current.get()
                if value is not None:
                    value["ordinary_sql_seconds"] = 0.01

            await asyncio.to_thread(sync_work)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        async def send(message):
            pass

        async def receive():
            return {"type": "http.request"}

        await RequestTelemetry(downstream, Telemetry(), diagnostic=enabled)(
            {
                "type": "http",
                "method": "GET",
                "headers": [
                    (b"traceparent", b"00-11111111111111111111111111111111-2222222222222222-01")
                ],
            },
            receive,
            send,
        )
        assert current.get() is None

    with caplog.at_level(logging.INFO, logger="foundry.operations"):
        asyncio.run(run(True))
        assert '"ordinary_sql_seconds": 0.01' in caplog.text
        assert '"trace_id": "11111111111111111111111111111111"' in caplog.text
        caplog.clear()
        asyncio.run(run(False))
        assert '"timings"' not in caplog.text
