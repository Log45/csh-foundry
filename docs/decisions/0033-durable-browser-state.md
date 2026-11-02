# ADR 0033 — Encrypted PostgreSQL browser state through an internal application service

Accepted for Phase 10. Retain PostgreSQL and governed Python services rather than add Redis or
give Next database credentials. Next calls a fixed internal API, authenticated with a distinct
256-bit service credential. The BFF contract excludes these routes; ingress denies `/internal/`.
The internal credential is not an API bearer token and grants no domain permission.

Migration 0016 stores SHA256 opaque-handle digests, authenticated ciphertext, expiry and revision.
Fernet/MultiFernet from cryptography provides established authenticated encryption and a key ring.
The encrypted envelope binds kind and row key, preventing ciphertext swaps. The first key encrypts;
retained keys decrypt. Every login consume and logout deletion locks/deletes the shared row in one
transaction. Session updates require the current revision and cannot extend expiry or resurrect a
deleted row. Admission is serialized across replicas and bounded, with expired-state cleanup.

Browser sessions retain API tokens only. No browser refresh token, localStorage token, ID-token
session credential or custom token issuance is introduced. Reauthentication rotates the opaque ID
and CSRF value and invalidates the preceding session. Lifetime is bounded by signed token expiry
and one hour; selected Keycloak access tokens last five minutes. Silent refresh is unsupported.
New workers obtain fresh standard client-credential tokens per supervised child invocation.

API authorizers recheck current principals/memberships/roles/policies; the session store never
caches permission authority. Logout invalidates shared state first, then offers standard broker
logout with client_id and a fixed post-logout redirect. Broker outages cannot prevent local logout.
Previously issued API JWTs remain valid until expiry unless platform authority is revoked.

Internal network and operator credentials are trust boundaries. The minimum profile runs this
internal hop on an isolated Docker bridge on one host; remote/multi-host transport requires TLS
and a separate review. Database loss fails session requests closed. Production requires durable
state and explicit HTTPS origins; memory mode is retained only for development tests.

Tests include two independent stores, ciphertext confidentiality, key rotation, single-use races,
CAS conflicts, logout/update races, expiry, capacity and internal authentication. Two built Next
processes share a real PostgreSQL session and survive replica restart; logout rejects the other
replica. Multi-region replication and mixed-release rolling upgrades are unsupported.
