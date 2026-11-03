"""Shared request admission, redacted request spans and bounded metrics."""

import asyncio
import hashlib
import json
import logging
import re
import secrets
import threading
import time
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ontology_platform.errors import ApplicationError

log = logging.getLogger("foundry.operations")


class TransportBounds:
    """Bound request parsing and response buffering before any bytes are disclosed."""

    def __init__(
        self,
        app: ASGIApp,
        request_bytes: int = 1048576,
        response_bytes: int = 8388608,
        deadline: float = 60,
    ):
        self.app = app
        self.request_bytes, self.response_bytes, self.deadline = (
            request_bytes,
            response_bytes,
            deadline,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request: list[bytes] = []
        size = 0
        output: list[Message] = []
        response_size = 0

        async def collect(message: Message) -> None:
            nonlocal response_size
            response_size += len(message.get("body", b""))
            if response_size > self.response_bytes:
                raise ApplicationError("response_limit", "Response exceeds configured limit", 503)
            output.append(message)

        try:
            async with asyncio.timeout(self.deadline):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    size += len(chunk)
                    if size > self.request_bytes:
                        raise ApplicationError(
                            "request_limit", "Request exceeds configured limit", 413
                        )
                    request.append(chunk)
                    if not message.get("more_body", False):
                        break
                consumed = False

                async def replay() -> Message:
                    nonlocal consumed
                    if consumed:
                        return await receive()
                    consumed = True
                    return {"type": "http.request", "body": b"".join(request), "more_body": False}

                await self.app(scope, replay, collect)
        except Exception as error:
            # Never let driver exceptions/parameters or arbitrary payload details reach server logs.
            failure = (
                error
                if isinstance(error, ApplicationError)
                else (
                    ApplicationError("request_timeout", "Request deadline exceeded", 504)
                    if isinstance(error, TimeoutError)
                    else ApplicationError("internal_error", "An internal error occurred", 500)
                )
            )
            await JSONResponse(
                {"error": {"code": failure.code, "message": failure.message}},
                status_code=failure.status_code,
            )(scope, receive, send)
            return
        for message in output:
            await send(message)


def rate_limit(sessions: sessionmaker[Session], identity: str, limit: int) -> None:
    """Atomic fixed-minute budget across replicas, using the database clock."""
    key = hashlib.sha256(identity.encode()).hexdigest()
    with sessions.begin() as session:
        count = session.scalar(
            text("""
            INSERT INTO request_budgets(key, window_minute, count)
            VALUES (:key, floor(extract(epoch FROM clock_timestamp()) / 60)::bigint, 1)
            ON CONFLICT (key) DO UPDATE SET
              count = CASE WHEN request_budgets.window_minute = excluded.window_minute
                           THEN request_budgets.count + 1 ELSE 1 END,
              window_minute = excluded.window_minute
            RETURNING count
        """),
            {"key": key},
        )
    if count is not None and count > limit:
        raise ApplicationError("rate_limited", "Request budget exceeded", 429)


class Telemetry:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests: Counter[tuple[str, str]] = Counter()
        self.duration: dict[str, float] = {}
        self.buckets: Counter[tuple[str, float]] = Counter()

    def observe(self, route: str, status: int, elapsed: float) -> None:
        with self.lock:
            self.requests[(route, str(status))] += 1
            self.duration[route] = self.duration.get(route, 0.0) + elapsed
            for bound in (0.1, 0.5, 1.0, 5.0, 30.0, 60.0, float("inf")):
                if elapsed <= bound:
                    self.buckets[(route, bound)] += 1

    def render(self) -> str:
        with self.lock:
            lines = ["# TYPE foundry_requests_total counter"]
            for (route, status), count in sorted(self.requests.items()):
                label = json.dumps(route)
                lines.append(f'foundry_requests_total{{route={label},status="{status}"}} {count}')
            lines.append("# TYPE foundry_request_seconds histogram")
            for (route, bound), count in sorted(self.buckets.items()):
                value = "+Inf" if bound == float("inf") else str(bound)
                lines.append(
                    f"foundry_request_seconds_bucket{{route={json.dumps(route)},"
                    f'le="{value}"}} {count}'
                )
            for route, total in sorted(self.duration.items()):
                count = sum(n for (r, _), n in self.requests.items() if r == route)
                lines.extend(
                    [
                        f"foundry_request_seconds_sum{{route={json.dumps(route)}}} {total}",
                        f"foundry_request_seconds_count{{route={json.dumps(route)}}} {count}",
                    ]
                )
            return "\n".join(lines) + "\n"


class RequestTelemetry:
    def __init__(self, app: ASGIApp, telemetry: Telemetry, diagnostic: bool = False):
        self.app, self.telemetry = app, telemetry
        self.diagnostic = diagnostic

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from ontology_platform.diagnostics import current

        timing: dict[str, float] = {}
        timing_token = current.set(timing if self.diagnostic else None)
        started = time.monotonic()
        parent = dict(scope.get("headers", [])).get(b"traceparent", b"").decode("ascii", "ignore")
        match = re.fullmatch(r"00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})", parent)
        trace = (
            match[1] if match and int(match[1], 16) and int(match[2], 16) else secrets.token_hex(16)
        )
        span = secrets.token_hex(8)
        status = 500

        async def traced(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-request-id", span.encode()),
                        (b"traceparent", f"00-{trace}-{span}-01".encode()),
                        (b"cache-control", b"no-store"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, traced)
        finally:
            elapsed = time.monotonic() - started
            template = str(getattr(scope.get("route"), "path", "unmatched"))
            self.telemetry.observe(template, status, elapsed)
            log.info(
                json.dumps(
                    {
                        "event": "request_span",
                        "timestamp": datetime.now(UTC).isoformat(),
                        "trace_id": trace,
                        "span_id": span,
                        "route": template,
                        "method": scope["method"],
                        "status": status,
                        "duration_seconds": round(elapsed, 6),
                        **({"timings": timing} if self.diagnostic else {}),
                    }
                )
            )
            current.reset(timing_token)
