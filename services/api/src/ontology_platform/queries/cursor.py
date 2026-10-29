"""Signed opaque API tokens. No unselected sort/property values enter the payload."""

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from ontology_platform.errors import ApplicationError


def canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class CursorCodec:
    def __init__(self, key: bytes | None = None):
        self.key = key or secrets.token_bytes(32)
        if len(self.key) < 32:
            raise ValueError("Cursor key must contain at least 32 bytes")

    def bind(self, value: Any, *, purpose: str) -> str:
        return hmac.digest(
            self.key, purpose.encode() + b"\0" + canonical(value).encode(), "sha256"
        ).hex()

    def encode(self, payload: dict[str, Any]) -> str:
        data = canonical(payload | {"v": 1, "issued": int(time.time())}).encode()
        signature = hmac.digest(self.key, b"token-v1\0" + data, "sha256")
        token = base64.urlsafe_b64encode(data + signature).decode().rstrip("=")
        if len(token) > 16_384:
            raise ApplicationError(
                "cursor_too_large", "Identity exceeds cursor bounds; use offset pagination", 422
            )
        return token

    def decode(self, token: str) -> dict[str, Any]:
        try:
            if len(token) > 16_384:
                raise ValueError("Oversized cursor")
            raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
            data, signature = raw[:-32], raw[-32:]
            if not hmac.compare_digest(
                signature, hmac.digest(self.key, b"token-v1\0" + data, "sha256")
            ):
                raise ValueError("Invalid signature")
            result = json.loads(data)
            if (
                not isinstance(result, dict)
                or result.get("v") != 1
                or type(result.get("issued")) is not int
                or not -5 <= time.time() - result["issued"] <= 3600
            ):
                raise ValueError("Invalid or expired cursor")
            return result
        except (ValueError, TypeError, UnicodeError) as exc:
            raise ApplicationError("invalid_cursor", "Cursor is invalid or expired", 400) from exc
