"""Internal encrypted session persistence. This grants no domain authorization."""

import hmac
import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from fastapi import APIRouter, Header, Request
from pydantic import Field, JsonValue
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from ontology_platform.config import Settings
from ontology_platform.contracts import APIModel
from ontology_platform.db.models import BrowserState
from ontology_platform.errors import ApplicationError

Kind = Literal["login", "session"]
router = APIRouter(prefix="/internal/browser-state", include_in_schema=False)


class StateInput(APIModel):
    data: dict[str, JsonValue]
    expires: int = Field(gt=0)
    revision: int = Field(default=0, ge=0)


class StateOutput(StateInput):
    pass


class BrowserStore:
    def __init__(self, sessions: sessionmaker[Session], settings: Settings):
        self.sessions = sessions
        self.capacity = settings.browser_state_capacity
        self.secret = settings.browser_state_secret
        self.cipher = (
            MultiFernet(
                [
                    Fernet(k.strip())
                    for k in settings.browser_state_keys.get_secret_value().split(",")
                ]
            )
            if settings.browser_state_keys
            else None
        )

    def authenticate(self, credential: str | None) -> None:
        if (
            not self.secret
            or not credential
            or not hmac.compare_digest(
                credential.encode(), ("Bearer " + self.secret.get_secret_value()).encode()
            )
        ):
            raise ApplicationError("forbidden", "Internal service authentication required", 403)

    def unpack(self, row: BrowserState) -> StateOutput:
        assert self.cipher is not None
        try:
            value = json.loads(self.cipher.decrypt(row.ciphertext))
            if value["kind"] != row.kind or value["key"] != row.key:
                raise ValueError("Ciphertext binding mismatch")
            return StateOutput(
                data=value["data"],
                expires=int(row.expires_at.timestamp() * 1000),
                revision=row.revision,
            )
        except (InvalidToken, ValueError, KeyError, TypeError) as exc:
            raise ApplicationError("session_unavailable", "Session decryption failed", 503) from exc

    def operate(
        self, kind: Kind, key: str, method: str, body: StateInput | None = None
    ) -> StateOutput:
        import re

        if self.cipher is None:
            raise ApplicationError("session_unavailable", "Session persistence is disabled", 503)
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", key):
            raise ApplicationError("invalid_session", "Invalid session identifier", 400)
        with self.sessions.begin() as session:
            now = session.scalar(select(func.clock_timestamp()))
            assert isinstance(now, datetime)
            if method == "PUT":
                # Serialize admission across replicas; expiration cleanup cannot resurrect rows.
                session.execute(text("SELECT pg_advisory_xact_lock(714002, 1)"))
                session.execute(delete(BrowserState).where(BrowserState.expires_at <= now))
                count = session.scalar(
                    select(func.count()).select_from(BrowserState).where(BrowserState.kind == kind)
                )
                if count is not None and count >= self.capacity:
                    raise ApplicationError("session_capacity", "Session capacity reached", 503)
            row = session.get(BrowserState, (kind, key), with_for_update=True)
            if method == "PUT":
                if row is not None or body is None or body.revision != 0:
                    raise ApplicationError("session_conflict", "Session already exists", 409)
                expiry = datetime.fromtimestamp(body.expires / 1000, UTC)
                ttl = (expiry - now).total_seconds()
                if not 0 < ttl <= (300 if kind == "login" else 3600):
                    raise ApplicationError("invalid_session", "Invalid session lifetime", 400)
                row = BrowserState(kind=kind, key=key, expires_at=expiry, revision=1)
                session.add(row)
            elif row is None or row.expires_at <= now:
                raise ApplicationError("session_expired", "Session expired", 401)
            elif method == "PATCH":
                if kind != "session" or body is None or body.revision != row.revision:
                    raise ApplicationError(
                        "session_conflict", "Session changed; retry request", 409
                    )
                if body.expires != int(row.expires_at.timestamp() * 1000):
                    raise ApplicationError("invalid_session", "Session extension forbidden", 400)
                row.revision += 1
            if method in {"PUT", "PATCH"}:
                assert body is not None
                plaintext = json.dumps({"kind": kind, "key": key, "data": body.data}).encode()
                if len(plaintext) > 23000:
                    raise ApplicationError("invalid_session", "Session payload too large", 413)
                row.ciphertext = self.cipher.encrypt(plaintext)
                session.flush()
            output = self.unpack(row)
            if method == "DELETE":
                session.delete(row)
            return output


def store(request: Request, authorization: str | None) -> BrowserStore:
    result: BrowserStore = request.app.state.browser_store
    result.authenticate(authorization)
    return result


@router.get("/{kind}/{key}")
def get_state(
    request: Request, kind: Kind, key: str, authorization: Annotated[str | None, Header()] = None
) -> StateOutput:
    if kind == "login":
        raise ApplicationError("forbidden", "Login state is consume-only", 403)
    return store(request, authorization).operate(kind, key, "GET")


@router.delete("/{kind}/{key}")
def consume_state(
    request: Request, kind: Kind, key: str, authorization: Annotated[str | None, Header()] = None
) -> StateOutput:
    return store(request, authorization).operate(kind, key, "DELETE")


@router.put("/{kind}/{key}")
def create_state(
    request: Request,
    kind: Kind,
    key: str,
    body: StateInput,
    authorization: Annotated[str | None, Header()] = None,
) -> StateOutput:
    return store(request, authorization).operate(kind, key, "PUT", body)


@router.patch("/{kind}/{key}")
def update_state(
    request: Request,
    kind: Kind,
    key: str,
    body: StateInput,
    authorization: Annotated[str | None, Header()] = None,
) -> StateOutput:
    return store(request, authorization).operate(kind, key, "PATCH", body)
