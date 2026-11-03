"""Validation boundary only; no local approval keys or production authorizer exist.

An independently configured release approval service must verify the detached signature
AND the signer's authority. The release CLI deliberately supplies no such service.
"""

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

AuthorizationVerifier = Callable[[bytes, str, str, str], bool]
BINDINGS = frozenset(
    {
        "advisory",
        "image_id",
        "config_digest",
        "package_name",
        "package_version",
        "package_purl",
        "scanner_sha256",
        "sbom_sha256",
        "technical_evidence_sha256",
    }
)
FIELDS = BINDINGS | {"decision", "authority", "issued_at", "expires_at"}


def validate_disposition(
    envelope: dict[str, Any],
    finding: dict[str, str],
    *,
    now: datetime,
    authorizer: AuthorizationVerifier | None = None,
) -> dict[str, Any]:
    """Validate exact evidence bindings before consulting an external trust boundary.

    This does not itself grant an exception or change raw scanner findings. The callback
    must not trust keys/identities carried by the envelope or supplied by its developer.
    """
    if set(envelope) != {"payload", "signer", "signature"}:
        raise ValueError("Signed disposition envelope required")
    payload = envelope["payload"]
    if not isinstance(payload, dict) or set(payload) != FIELDS:
        raise ValueError("Incomplete or unknown disposition fields")
    if any(not isinstance(v, str) or not v.strip() for v in payload.values()):
        raise ValueError("Nonempty string disposition fields required")
    if set(finding) != BINDINGS or any(payload[k] != finding[k] for k in BINDINGS):
        raise ValueError("Disposition does not match current finding/evidence")
    for name in ("image_id", "config_digest"):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", payload[name]):
            raise ValueError("Immutable image digest required")
    for name in ("scanner_sha256", "sbom_sha256", "technical_evidence_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", payload[name]):
            raise ValueError("Evidence SHA256 required")
    if payload["decision"] not in {"accept_risk", "confirm_remediated", "confirm_not_affected"}:
        raise ValueError("Unapproved disposition decision")
    issued = datetime.fromisoformat(payload["issued_at"])
    expires = datetime.fromisoformat(payload["expires_at"])
    if any(t.tzinfo is None for t in (issued, expires, now)):
        raise ValueError("Timezone-aware disposition dates required")
    if not issued <= now.astimezone(UTC) < expires:
        raise ValueError("Expired or not-yet-valid disposition")
    signer, signature = envelope["signer"], envelope["signature"]
    if not isinstance(signer, str) or not signer or not isinstance(signature, str) or not signature:
        raise ValueError("Signer and signature required")
    if authorizer is None:
        raise ValueError("Independent disposition authorization unavailable; promotion blocked")
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    if not authorizer(canonical, signer, signature, payload["authority"]):
        raise ValueError("Invalid signature or unauthorized signer/authority")
    return payload
