# Phase 10 — OKD4 deployment readiness

| Assessment | Result | Basis |
|---|---|---|
| Implementation | **PASS** | Portable resources, arbitrary-UID images, external-infrastructure contracts, storage/migration/security tooling and final application checks implemented |
| Local acceptance | **BLOCKED** | Raw application-image high findings remain; successful local tests do not waive security gates |
| Production-like acceptance | **BLOCKED** | Security/approval gates and an actual approved Kubernetes/OKD target remain unavailable; target execution NOT RUN |
| Production certification | **NOT RUN** | Organization identity/infrastructure approval, off-host recovery, monitoring ownership and capacity/handoff not supplied |

**Release gate BLOCKED; container security FAIL; no exception authorized.** No image publication,
organizational deployment, schema migration or Phase 11 implementation occurred.

Starting revision: `0127f805a0bbb773b5da38b0d062fba7ae7b129b`, clean tree. The user subsequently
committed future-roadmap changes in `dfdda5f3c0307a3e694b52cb332445c797221373`; those changes are
preserved and do not authorize future phases. This implementation remains uncommitted.
[Changed-file inventory](changed-files.json) lists every created/modified file and its hash;
`SHA256SUMS` binds all public evidence. Existing historical evidence and developer resources remain
unchanged. Final running container names match the original inventory; owned test resources were
cleaned. Private test credentials, realm exports, backups/WAL, raw scans and browser traces stay
under ignored `artifacts/` / `apps/studio/test-results/`.

## Implementation and architecture

- `infrastructure/kubernetes/base`: API/Studio Services and Deployments, ingestion/semantic/outbox
  Deployments (outbox disabled until configured), ServiceAccount, public ConfigMap, default-deny
  NetworkPolicies, scoped volumes, resource budgets and startup/readiness/liveness probes.
- `overlays/okd`: HTTPS Studio Route with redirects/HSTS and ingress policy. No application-owned
  PostgreSQL, Keycloak, nginx or S3 workload. API internal endpoints remain namespace-private.
- `overlays/self-hosted`: the same application base with an allowed supplemental volume group;
  ingress policy remains site-specific. Optional file-source component mounts an existing shared
  read-only claim for registered CSV/Parquet sources. PostgreSQL ingestion needs no source volume.
- Dedicated migration Job/credentials and explicit maintenance rollout command. Same-session
  PostgreSQL advisory lock, no automatic destructive reset/downgrade, migration/drift success before
  application rollout. Operators serialize rollout commands; the DB lock does not coordinate Job
  deletion by two release operators. **No new migrations; head `0017_capacity`.**
- Numeric image defaults with no fixed UID in OKD manifests. Arbitrary nonzero UIDs and unrelated
  nonzero GIDs work with immutable roots, no capabilities and bounded `/tmp`; no group0 assumption.
  Python avoids bytecode/user-site/home writes; Next cache is scoped to temporary storage.
- Studio retains Next.js/BFF and durable PostgreSQL sessions. Optional Compose nginx uses a pinned
  maintained unprivileged supplier image, supported stable updates and removal of unused curl/modules,
  8080/8443 listeners and temporary configuration. An explicit trusted-origin backchannel socket port
  preserves public OIDC issuer/signature/audience/TLS checks. OKD uses the normal external endpoint.
- Storage audit retains PostgreSQL artifacts, sessions, objects, jobs and outbox. **S3 is not required
  for the current OKD4 deployment**, and none was introduced. Source files remain externally owned
  inputs requiring shared/reproducible availability during retry. Pod-local durable state is not used.
- Reproduced Studio refresh suppression while workspace busy; activation now awaits direct refresh
  and stale request generations cannot overwrite newer reads. Original incident remains historical;
  the reproduced mechanism is not asserted to be its sole cause. A trace captures the activation
  response, subsequent ontology/version reads and `Active 1.0.0` header with request timing.
- Profile-aware release verification preserves the six-image Compose gate; OKD requires exactly three
  application images plus explicit hashed external-service, rendered-config and Secret/ConfigMap
  identity evidence. Missing services/images/gates and raw high/critical findings remain blocking.

Read the [deployment guide](../../../operations/okd4-deployment.md),
[administrator request](../../../operations/okd4-infrastructure-request.md),
[storage audit](../../storage-audit.md), and
[architecture decision](../../../decisions/0035-portable-restricted-deployment.md).
The [deployment-specific BOM](deployment-bom.json) distinguishes owned images from externally
maintained services without declaring those services vulnerability-free.

## Executed validation

| Check | Result | Evidence |
|---|---|---|
| Python regression | **PASS 625**, one strict xfail, **zero skips** | `raw/confirmed-python.txt`, `regression-results.json` |
| Frontend | **PASS 33** | `raw/confirmed-frontend.txt` |
| Browser | **PASS 5 + 5**, bounded runs under concurrent regression load | `raw/final-latest-browser-concurrent-{1,2}.txt`, `browser-consistency.json` |
| Lint / formatting / strict mypy / TS typecheck | **PASS**; mypy 98 source files | `raw/*`, `regression-results.json` |
| Production build | **PASS** standalone host build and selected image builds | Private build logs named in command inventory |
| Migration/drift | **PASS**, head unchanged | `raw/confirmed-migrations.txt`; integration lock/ordering negatives in full suite |
| Arbitrary UID/GID runtime | **PASS 8 image runs**, two UID/GID pairs, no root group/capabilities, read-only roots | `non-root-validation.json`, `container-compatibility.json` |
| Migration container | **PASS** arbitrary UID with verified-TLS PostgreSQL | `raw/migration-nonroot.txt` |
| Selected-image combined deployment | **PASS 39 assertions / 36 distinct checks** | `release-candidate/deployment.json` and `raw/release-candidate.txt` |
| Multiple workers/API replicas | **PASS 9 checks**, two ingestion workers and two API replicas; conflicts/idempotency/branch preconditions/shared admission/audit rollback | `replicas-selected/deployment.json`, `raw/replicas-selected.txt` |
| PostgreSQL TLS / wrong credentials / invalid CA / unavailable service | **PASS** disposable 17.11 | `postgres-integration.json`, `raw/confirmed-postgres-tls.txt` |
| Keycloak Code/PKCE / token contract | **PASS** disposable 26.8.1, no live organization federation | `keycloak-integration.json`, `raw/keycloak.txt` |
| OWLAPI import/export | **PASS** actual 4.5.29 RDF/XML roundtrip | `raw/protege.txt`; manual authoring UI NOT RUN |
| Kustomize contract | **PASS** base16 / OKD18 / self-hosted16 / migration1 resources | `kubernetes-validation.json` and full regression |
| Strict Kubernetes schema | **PASS 34 resources**, zero invalid/errors; **one Route skipped** | `raw/kubeconform.txt`; Route source/local-contract checks only |
| Actual server dry-run / OKD SCC / cross-node storage | **NOT RUN** no configured suitable cluster | `kubernetes-validation.json` |
| Optional nginx TLS and callback log redaction | **PASS**, including failed upstream and both stdout/stderr | `raw/ingress-log-redaction-final.txt` |
| API/Studio/semantic scan | **FAIL: 56 / 55 / 56 high**, zero critical | `supply-chain-binding.json`, `security-assessment.json` |
| Optional minimized unprivileged nginx scan | **PASS: zero high/critical**, three medium | `supply-chain-binding.json` |
| Actual release verifier | **BLOCKED: container_security not PASS** | `release-gate-result.json` |

Combined checks include canonical 63 objects/70 links, action replay/conflict behavior, worker
SIGKILL/checkpoint reclaim, semantic validation/reasoning and operational isolation, independently
installed Python/TypeScript SDKs, branch merge, real privilege checks, credential rotation, logical
restore, complete-profile PostgreSQL physical PITR, compatible image rollback, two Studio replicas,
restart continuity, fail-closed session-store outage, logout and HTTPS authorization/CSRF boundaries.

`fixture-validation.json` reports each applicable `fixtures/VALIDATION.md` category. The raw pySHACL
string-term mismatch remains a strict expected failure; normalized conformance and pinned engine
checks pass. The base OWL-RL classification limitation remains NOT SUPPORTED, and independent Lean
proof checking/manual Protégé UI are NOT RUN. No skipped/unexecuted check is counted as PASS.

## Reproduction and evidence boundaries

Use Node >=22 on PATH and a disposable verified-TLS PostgreSQL database for the complete Python
suite. Existing integration tests create unique migrated schemas and drop only their own schemas.
The full test database must also be migrated for the database-readiness test. Never select the
shared development database for destructive migration/recovery checks.

```bash
uv run pytest -ra --tb=short
uv run ruff check .
uv run ruff format --check .
uv run mypy
npm test --prefix apps/studio
npm run typecheck --prefix apps/studio
uv run python scripts/test_nonroot_containers.py --output /private/new-nonroot.json
uv run python scripts/test_external_postgres.py
uv run python scripts/accept_okd4_local.py --candidate-images CANDIDATE.json --output NEW_DIRECTORY
uv run python scripts/accept_okd4_local.py --scope replicas --candidate-images CANDIDATE.json --output ANOTHER_NEW_DIRECTORY
```

The exact Node25 PATH, disposable TLS setup, browser ports/directories and each executed command
are recorded in `commands.json` and raw-output inventory. These are local Docker surrogates, not
Kubernetes deploy commands. Test-only CA/identity transport does not certify live infrastructure.
Trace archives contain sensitive callback/session data and remain private; only a filtered
activation timing/version attachment is included in public evidence. Raw SBOMs/scans are bound by
hash and retain execution identities. Local image IDs are not published registry manifest digests.
The selected Docker images match current API/semantic runtime source hashes; Studio has compiled
standalone build/runtime evidence. Later changes to host-only acceptance tools/documentation do
not claim a rebuild of those immutable image layers.

`execution-attempts.json` retains setup/test-harness failures: initially unmigrated disposable DB,
occupied development browser port, old host Node, verifier mock signature, unsupported emulated
Polars operation, probe temporary-path config and intentional SIGTERM exit-code interpretation.
The failed pre-minimization nginx scan (39 high/15 critical) remains preserved; only supported
removal/updates changed its final inventory. Historical developer/security evidence was not rewritten.
The full combined application run preceded final critical-only nginx error-log tightening; the
final callback/upstream-failure test separately validates that more restrictive setting. The
selected replica run uses the final template. No exact production configuration approval is claimed.

## Remaining blockers and next work

- **Security remediation:** 167 application-image high matches block the OKD application gate.
  Historical PostgreSQL libxml2 critical remains vendor-dependent; the Keycloak trust-store match
  still requires independent disposition authorization. External service ownership does not waive
  patching or approval. No vulnerability exception or independent authorizer was installed.
- **Independent approval:** no organization publication/deployment/release/risk approval or named
  handoff owners. The release CLI still rejects advisory dispositions without a trusted authorizer.
- **Infrastructure prerequisites:** actual cluster version/SCC/group ranges, registry/architecture,
  external PostgreSQL/Keycloak endpoints/CAs/client configuration, quota, Route TLS/CNI policy,
  Secrets and optional shared source claim require administrator input.
- **Compatibility:** pinned Linux ARM64 semantic binary is unavailable; semantic scheduling selects
  AMD64. Namespace-internal HTTP hops need organization approval or separately reviewed service TLS.
- **Unexecuted target validation:** actual Route schema/server dry-run/SCC admission, rescheduling,
  cross-node claim access, enforced network policies, live organizational identity, off-host recovery,
  production monitoring/capacity/secret management and operational handoff remain NOT RUN.

Continue these **Phase 10** remediation/approval/target checks. Phase 11 and the future roadmap are
not authorized. Local engineering success is not production approval.
