"""Test-only keys model an external authority; no key is installed for release use."""

import base64
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "dispositions", ROOT / "scripts/security_dispositions.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def signed_review():
    now = datetime(2026, 11, 3, tzinfo=UTC)
    finding = {
        "advisory": "CVE-2026-91403",
        "image_id": "sha256:" + "1" * 64,
        "config_digest": "sha256:" + "2" * 64,
        "package_name": "java-21-openjdk-headless",
        "package_version": "1:21.0.13.0.9-1.2.el9",
        "package_purl": "pkg:rpm/redhat/java-21-openjdk-headless@21.0.13.0.9-1.2.el9",
        "scanner_sha256": "3" * 64,
        "sbom_sha256": "4" * 64,
        "technical_evidence_sha256": "5" * 64,
    }
    payload = finding | {
        "decision": "confirm_remediated",
        "authority": "test-security-review",
        "issued_at": (now - timedelta(days=1)).isoformat(),
        "expires_at": (now + timedelta(days=1)).isoformat(),
    }
    key = Ed25519PrivateKey.generate()
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    envelope = {
        "payload": payload,
        "signer": "test-only-authority",
        "signature": base64.b64encode(key.sign(canonical)).decode(),
    }

    def authorize(raw, signer, signature, authority):
        if signer != "test-only-authority" or authority != "test-security-review":
            return False
        try:
            key.public_key().verify(base64.b64decode(signature, validate=True), raw)
        except (InvalidSignature, ValueError):
            return False
        return True

    return envelope, finding, now, authorize


def test_validation_interface_requires_independent_authorizer(signed_review):
    envelope, finding, now, authorize = signed_review
    with pytest.raises(ValueError, match="authorization unavailable"):
        module.validate_disposition(envelope, finding, now=now)
    assert module.validate_disposition(envelope, finding, now=now, authorizer=authorize)


@pytest.mark.parametrize(
    "mutation",
    [
        "no_disposition",
        "missing_signature",
        "invalid_signature",
        "unknown_signer",
        "expired",
        "advisory",
        "image_id",
        "config_digest",
        "package_name",
        "package_version",
        "package_purl",
        "scanner_sha256",
        "sbom_sha256",
        "technical_evidence_sha256",
        "decision",
        "authority",
        "reused_image",
        "updated_image",
        "future",
        "naive",
        "resigned_self_exception",
    ],
)
def test_unauthorized_disposition_is_rejected(signed_review, mutation):
    envelope, finding, now, authorize = signed_review
    if mutation == "no_disposition":
        envelope = {}
    elif mutation == "missing_signature":
        del envelope["signature"]
    elif mutation in {"invalid_signature", "resigned_self_exception"}:
        envelope["signature"] = base64.b64encode(
            Ed25519PrivateKey.generate().sign(b"self")
        ).decode()
    elif mutation == "unknown_signer":
        envelope["signer"] = "developer"
    elif mutation == "expired":
        now += timedelta(days=2)
    elif mutation == "future":
        now -= timedelta(days=2)
    elif mutation == "naive":
        envelope["payload"]["expires_at"] = "2026-11-04"
    elif mutation in {"reused_image", "updated_image"}:
        finding["image_id"] = "sha256:" + "9" * 64
    else:
        envelope["payload"][mutation] = "modified"
    with pytest.raises(ValueError):
        module.validate_disposition(envelope, finding, now=now, authorizer=authorize)
