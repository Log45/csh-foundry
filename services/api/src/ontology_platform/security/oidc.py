"""Explicit trusted OIDC providers; RFC 9068 JWT access tokens, never ID tokens."""

import json
import threading
import time
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
import jwt
from pydantic import Field, model_validator

from ontology_platform.errors import ApplicationError
from ontology_platform.queries.ast import Name, QueryModel


def https_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port not in (None, 443)
        or any(ord(c) <= 32 for c in value)
    ):
        raise ValueError(
            "Trusted OIDC URLs require HTTPS port 443 without credentials/query/fragment"
        )
    return value


class Provider(QueryModel):
    id: Name
    issuer: str = Field(min_length=1, max_length=2048)
    audience: Name
    algorithms: tuple[Literal["RS256", "ES256"], ...] = ("RS256",)
    clients: tuple[Name, ...] = Field(min_length=1, max_length=32)
    clock_skew: int = Field(default=30, ge=0, le=60)
    cache_seconds: int = Field(default=300, ge=30, le=3600)

    @model_validator(mode="after")
    def valid(self) -> "Provider":
        https_url(self.issuer)
        if not self.algorithms:
            raise ValueError("At least one asymmetric algorithm required")
        return self


class OIDCVerifier:
    def __init__(self, providers: tuple[Provider, ...], *, client: httpx.Client | None = None):
        self.providers = providers
        self.client = client or httpx.Client(timeout=3, follow_redirects=False, trust_env=False)
        self.cache: dict[str, tuple[float, dict[str, dict[str, Any]]]] = {}
        self.attempts: dict[str, float] = {}
        self.lock = threading.Lock()

    def document(self, url: str) -> dict[str, Any]:
        started = time.monotonic()
        content = bytearray()
        with self.client.stream("GET", url, follow_redirects=False) as response:
            if response.status_code != 200:
                raise ValueError("OIDC endpoint unavailable")
            # raw bytes also bound compressed bodies; compressed responses are excluded.
            if response.headers.get("content-encoding", "identity") != "identity":
                raise ValueError("Compressed metadata unsupported")
            for chunk in response.iter_raw():
                content.extend(chunk)
                if len(content) > 262144 or time.monotonic() - started > 5:
                    raise ValueError("OIDC response bound exceeded")
        result = json.loads(content)
        if not isinstance(result, dict):
            raise ValueError("OIDC document must be an object")
        return result

    def refresh(self, provider: Provider) -> dict[str, dict[str, Any]]:
        now = time.monotonic()
        # Rate-bound unknown-key refresh and failures as well as successful caches.
        if now - self.attempts.get(provider.id, -1000) < 30:
            raise ValueError("OIDC refresh rate limited")
        self.attempts[provider.id] = now
        metadata = self.document(provider.issuer.rstrip("/") + "/.well-known/openid-configuration")
        if metadata.get("issuer") != provider.issuer:
            raise ValueError("Discovery issuer mismatch")
        uri = metadata.get("jwks_uri")
        if not isinstance(uri, str):
            raise ValueError("Missing JWKS URI")
        https_url(uri)
        if urlsplit(uri).netloc != urlsplit(provider.issuer).netloc:
            raise ValueError("JWKS must share the configured issuer origin")
        keys = self.document(uri).get("keys")
        if not isinstance(keys, list) or not 1 <= len(keys) <= 32:
            raise ValueError("JWKS key count invalid")
        parsed: dict[str, dict[str, Any]] = {}
        for key in keys:
            if not isinstance(key, dict):
                raise ValueError("Malformed JWK")
            kid = key.get("kid")
            if not isinstance(kid, str) or not 1 <= len(kid) <= 200 or kid in parsed:
                raise ValueError("Missing/duplicate JWK identifier")
            parsed[kid] = key
        self.cache[provider.id] = (now + provider.cache_seconds, parsed)
        return parsed

    def warm(self) -> None:
        with self.lock:
            for provider in self.providers:
                self.refresh(provider)

    def verify(self, token: str) -> tuple[Provider, dict[str, Any]]:
        try:
            if len(token) > 16384:
                raise ValueError("Token bound")
            header = jwt.get_unverified_header(token)
            # Unverified issuer is ONLY a lookup into the fixed trusted configuration.
            claims = jwt.decode(token, options={"verify_signature": False})
            provider = next((p for p in self.providers if p.issuer == claims.get("iss")), None)
            if provider is None:
                raise ValueError("Untrusted issuer")
            alg, kid = header.get("alg"), header.get("kid")
            if (
                alg not in provider.algorithms
                or header.get("typ") not in ("at+jwt", "application/at+jwt")
                or not isinstance(kid, str)
                or len(kid) > 200
                or any(k in header for k in ("jku", "x5u", "jwk", "crit"))
            ):
                raise ValueError("Unsupported access token header")
            with self.lock:
                expiry, keys = self.cache.get(provider.id, (0, {}))
                if expiry <= time.monotonic() or kid not in keys:
                    keys = self.refresh(provider)
                key = keys.get(kid)
            if key is None or key.get("use", "sig") != "sig" or key.get("alg", alg) != alg:
                raise ValueError("Unsupported signing key")
            if "key_ops" in key and "verify" not in key["key_ops"]:
                raise ValueError("Key not intended for verification")
            if (alg == "RS256" and key.get("kty") != "RSA") or (
                alg == "ES256" and (key.get("kty"), key.get("crv")) != ("EC", "P-256")
            ):
                raise ValueError("Algorithm/key mismatch")
            if any(k in key for k in ("d", "p", "q", "k")):
                raise ValueError("Private signing material rejected")
            public_key = jwt.PyJWK(key, algorithm=alg).key
            if alg == "RS256" and public_key.key_size < 2048:
                raise ValueError("RSA key too small")
            verified = jwt.decode(
                token,
                public_key,
                algorithms=list(provider.algorithms),
                issuer=provider.issuer,
                audience=provider.audience,
                leeway=provider.clock_skew,
                options={"require": ["iss", "sub", "aud", "exp", "iat", "jti", "client_id"]},
            )
            if any(
                not isinstance(verified.get(k), str) or not verified[k].strip()
                for k in ("sub", "jti", "client_id")
            ):
                raise ValueError("Missing identity")
            if len(verified["sub"]) > 512 or verified["client_id"] not in provider.clients:
                raise ValueError("Untrusted client")
            if (
                verified.get("azp", verified["client_id"]) != verified["client_id"]
                or verified.get("token_use", "access") != "access"
            ):
                raise ValueError("Token use mismatch")
            if any(type(verified[k]) is not int for k in ("exp", "iat")) or (
                "nbf" in verified and type(verified["nbf"]) is not int
            ):
                raise ValueError("NumericDate integers required")
            if not 0 <= verified["iat"] < verified["exp"] <= 253402300799:
                raise ValueError("Invalid lifetime")
            return provider, verified
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, httpx.HTTPError) as exc:
            raise ApplicationError(
                "invalid_token", "A valid API access token is required", 401
            ) from exc
