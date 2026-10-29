"""Bounded at-least-once outbox runner. No network work in action transactions."""

import http.client
import ipaddress
import json
import socket
import ssl
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import select

from ontology_platform.db.governance import GovernedService
from ontology_platform.db.models import OutboxEvent, WebhookAttempt
from ontology_platform.errors import ApplicationError
from ontology_platform.security.interfaces import Principal


def destination(url: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ApplicationError("invalid_destination", "Invalid HTTPS destination", 422) from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
        or port not in {None, 443}
        or len(url) > 2048
        or any(ord(c) < 33 for c in url)
    ):
        raise ApplicationError(
            "invalid_destination",
            "HTTPS destination on port 443 without credentials/query required",
            422,
        )
    return parsed.hostname, parsed.path or "/"


def deliver(url: str, event_id: str, payload: dict[str, object]) -> int:
    host, path = destination(url)
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ApplicationError(
            "invalid_destination", "Destination must resolve exclusively to public addresses", 422
        )
    # Pin the validated address for this connection, retaining original hostname for TLS/SNI.
    address = str(addresses[0][4][0])

    class PinnedHTTPS(http.client.HTTPSConnection):
        def connect(self) -> None:
            raw = socket.create_connection((address, 443), timeout=5)
            try:
                self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
            except BaseException:
                raw.close()
                raise

    connection = PinnedHTTPS(host, timeout=5)
    try:
        connection.request(
            "POST",
            path,
            json.dumps(payload).encode(),
            {
                "Content-Type": "application/json",
                "X-Ontology-Event-ID": event_id,
            },
        )
        response = connection.getresponse()
        return response.status  # Response bodies and redirects are deliberately not followed.
    finally:
        connection.close()


class WebhookRunner(GovernedService):
    def run_one(
        self,
        principal: Principal,
        ontology_id: str,
        url: str,
        *,
        transport: Callable[[str, str, dict[str, object]], int] = deliver,
        now: datetime | None = None,
    ) -> UUID | None:
        destination(url)  # Server configuration only; never an action parameter or REST body.
        instant = now or datetime.now(UTC)
        with self.operation(principal, "outbox:deliver", ontology_id) as session:
            row = session.scalar(
                select(OutboxEvent)
                .where(
                    OutboxEvent.tenant_id == principal.tenant_id,
                    OutboxEvent.ontology_id == ontology_id,
                    OutboxEvent.status.in_(["PENDING", "CLAIMED"]),
                    OutboxEvent.next_attempt_at <= instant,
                )
                .order_by(OutboxEvent.next_attempt_at, OutboxEvent.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            if row.attempts >= 5:
                row.status, row.last_error = "DEAD", "lease_expired_at_attempt_limit"
                return row.id
            row.attempts += 1
            row.status, row.claim_token = "CLAIMED", uuid4()
            row.next_attempt_at = instant + timedelta(seconds=60)
            if row.destination is None:
                row.destination = url
            token, event_id, attempt, target = (
                row.claim_token,
                row.id,
                row.attempts,
                row.destination,
            )
            payload: dict[str, object] = {
                **row.payload,
                **{
                    "event_id": str(event_id),
                    "category": row.category,
                },
            }
            attempt_id = uuid4()
            session.add(
                WebhookAttempt(
                    tenant_id=principal.tenant_id,
                    ontology_id=ontology_id,
                    id=attempt_id,
                    event_id=event_id,
                    attempt=attempt,
                    outcome="UNKNOWN",
                )
            )
        # Claim transaction has committed and released every lock before HTTP.
        permanent = False
        try:
            status = transport(target, str(event_id), payload)
            success = 200 <= status < 300
            permanent = not success and status != 429 and not 500 <= status < 600
            outcome = f"http_{status}"
        except ApplicationError:
            success, permanent, outcome = False, True, "destination_rejected"
        except (OSError, http.client.HTTPException):
            success, outcome = False, "transport_failure"
        with self.operation(principal, "outbox:deliver", ontology_id) as session:
            row = session.scalar(
                select(OutboxEvent)
                .where(
                    OutboxEvent.tenant_id == principal.tenant_id,
                    OutboxEvent.ontology_id == ontology_id,
                    OutboxEvent.id == event_id,
                )
                .with_for_update()
            )
            if row is None or row.claim_token != token or row.status != "CLAIMED":
                return (
                    event_id  # Expired lease was reclaimed; stale completion cannot overwrite it.
                )
            history = session.get(WebhookAttempt, (principal.tenant_id, ontology_id, attempt_id))
            assert history is not None
            history.outcome = outcome
            row.status = (
                "DELIVERED" if success else ("DEAD" if permanent or attempt >= 5 else "PENDING")
            )
            row.last_error = None if success else outcome
            row.claim_token = None
            row.next_attempt_at = (now or datetime.now(UTC)) + timedelta(
                seconds=min(3600, 2**attempt)
            )
        return event_id


def main() -> None:
    import argparse

    from sqlalchemy.orm import sessionmaker

    from ontology_platform.config import get_settings
    from ontology_platform.db.session import make_engine
    from ontology_platform.security.local import LocalAuthorizer

    parser = argparse.ArgumentParser(
        description="Deliver up to 100 currently due action notifications"
    )
    parser.add_argument("--ontology", required=True)
    parser.add_argument(
        "--destination", required=True, help="Server-managed HTTPS URL, no query or credentials"
    )
    parser.add_argument("--max-events", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.max_events <= 100:
        parser.error("--max-events must be 1–100")
    configuration = get_settings()
    principal = Principal(
        tenant_id=configuration.local_tenant_id, principal_id=configuration.local_principal_id
    )
    engine = make_engine(configuration)
    try:
        runner = WebhookRunner(sessionmaker(engine), LocalAuthorizer(configuration))
        for _ in range(args.max_events):
            if runner.run_one(principal, args.ontology, args.destination) is None:
                break
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
