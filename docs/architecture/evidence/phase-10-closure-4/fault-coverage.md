# Local fault coverage

| Scenario | Result | Executed evidence / scope |
|---|---|---|
| Concurrent schema publication | PASS | attempt-1/deployment.json: eight attempts, one publish/seven version_immutable 409s; active version unchanged |
| Process loss after external outbox effect, before checkpoint | PASS | Actual loopback HTTP receiver and a child that exits 77 after successful delivery; no claim before lease expiry; same event retried after expiry; two deliveries/one deduplicated consumer effect; durable DELIVERED on attempt two |
| Outbox interruption scope | PASS runner/receiver | Injected loopback transport leaves production HTTPS/SSRF checks unchanged. This does not certify a deployed external receiver or confidential-worker supervisor lifecycle |
| Temporary storage cold-cache failure/recovery | PASS retry | Owned 16-MiB tmpfs only; FileNotFoundError with zero free blocks, then actual pinned-engine validation after freeing storage |
| Temporary storage warm-cache failure/recovery | PASS retry | Same bound; ENOSPC, then actual engine validation after freeing storage |
| Original temporary-storage probe | FAIL retained | attempt-1 expected ENOSPC on cold tempfile initialization; Python instead reported no usable directory. No platform failure or destructive host disk fill is inferred |
| Two-API action conflict/replay | PASS | Both scoped deployments: one commit/seven 409s; replay identical; one revision increment |
| Two-API stale branch merge | PASS | One commit/three 412 precondition failures; final provenance/revision checked |
| Two-API job admission/recovery/audit | PASS | Four admissions/four quota 409s, replay/cancel, rollback audit and zero final active jobs |
| Active delegated credential revocation before semantic output commit | PASS integration | Final full regression: test_security_workflows.py; completed external work produces no unauthorized persisted output |
| Authorization revocation immediately before commit | PASS integration | test_security_platform.py transaction/security-lock serialization and branch permission tests |
| Audit persistence failure during governed mutation | PASS integration | test_audit_failure_rolls_back_authorized_mutations; separate bounded audit pool retained |
| Ordinary/audit pool exhaustion, timeout, recovery/shutdown | PASS integration | test_capacity_acceptance.py; original limits unchanged |
| Duplicate claims, expired lease/fencing, worker concurrency admission | PASS integration | Full ingestion/semantic/security/capacity regressions; previous deployed crash recovery remains retained |
| Logical artifact/staging exhaustion and rollback | PASS integration | Full capacity tests; existing deployed two-tenant quota evidence retained |
| Shared physical database/host disk exhaustion | NOT RUN | No isolated physical failure domain authorized; do not fill shared Docker/host storage. Logical quota and bounded tmpfs results do not certify host disk behavior |
| Full target long-duration/queued/executing fault matrix | NOT RUN | Existing deterministic DB/fencing tests are not a complete target supervisor/failure-domain certification |
| Existing PITR, restored applications, broker/JWKS/signing/SDK faults and local alerts | PASS retained scope | Closure 3 unchanged; PostgreSQL/Keycloak images and recovery format were not changed, so full drills were not needlessly repeated |

All fixture mutations are confined to disposable databases. Receiver state is transient; named
volumes/containers are removed per project. The platform remains at-least-once for outbox effects;
consumer deduplication by stable event ID is required. No exactly-once external delivery is claimed.
