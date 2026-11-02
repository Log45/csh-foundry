# Phase 10 acceptance-closure evidence (2026-11-02)

Starting revision: `e7de0616c37b4afe7f5b2eddcbde99687d63f10e`. No pre-existing worktree changes.
The initial-status snapshot includes the evidence directory created by this task; it is not a user
change. No migration was created. Head/current/drift: `0017_capacity`. The working patch remains
uncommitted and `files.txt` inventories it. Application/container source identities are distinct from
production approval. Retained historical Phase 10 evidence was not replaced.

Environment: macOS ARM64, Docker Desktop Linux/arm64 28.3.0 / Compose 2.38.1, host Python 3.12.0,
uv 0.7.11, Node 25.9.0. Production images use pinned Python/Node/uv bases; semantic execution uses
amd64 emulation with the pinned Open Ontologies binary. New isolated schemas or uniquely named
Compose projects use disposable identities, private test CA, random loopback ports and separate
volumes/networks. No production resource is used. The operator's existing local database and broker
configuration/credentials are preserved.

| Check | Command / procedure | Result | Evidence / limit |
|---|---|---|---|
| Baseline Python, lint, format, mypy, migration drift | `PATH=/opt/homebrew/opt/node/bin:$PATH uv run python scripts/validate_phase0.py` | PASS | baseline.txt: 521 passed, 1 strict xfail, 0 skipped |
| Final configured full Python regression | Same command after application changes | PASS | regression-final.txt: 525 passed, 1 strict xfail, 0 skipped; regression-release.txt: final repeat 525/1/0 in 353.28 seconds |
| Ruff / strict mypy | `uv run ruff check .`; `uv run ruff format --check .`; `uv run mypy` | PASS | static-final.txt; final commands repeated after configuration edits |
| Alembic | `uv run alembic heads`; `current`; `check` | PASS | migrations.txt; 0017_capacity; upgrade/downgrade in isolated pytest schemas |
| Frontend tests/typecheck/build/format | `npm test`; `npm run typecheck`; `npm run build`; `npm run format:check` in apps/studio with Node >=22 | PASS | frontend-final.txt: 27 tests; frontend-format.txt |
| Browser E2E with durable replicas | `STUDIO_E2E_DURABLE=true uv run python scripts/test_studio.py` | PASS | browser-final.txt: 5 passed. browser.txt retains an initial activation assertion failure |
| Security, tenant isolation, branching, SDK, ingestion/recovery, semantic, OWL import/export | Configured full pytest suite above | PASS | Full suites executed against real PostgreSQL and engine; not separate invented test runs |
| Fixture Turtle/CSV/identity/FK contracts | Full fixture tests; fixture-sha256.json | PASS | Canonical fixtures unchanged; 6/20/12/25 and 63 objects/70 links |
| Raw pySHACL | Strict expected-failure test within full suite | FAIL (expected) | Existing simple/xsd:string mismatch retained; one XFAIL, not raw conformance |
| Normalized SHACL / Open Ontologies validation | Fixture/semantic suites and `uv run python scripts/semantic_smoke.py` | PASS | semantic-smoke.json/txt; historical output restored after copying new evidence |
| Base owl-rl CriticalMachine inference | Existing profile compatibility tests | NOT SUPPORTED | Known distinction from owl-rl-ext retained |
| Protégé/OWLAPI roundtrip | `mvn -q -f integrations/protege/pom.xml compile exec:java '-Dexec.args=fixtures/manufacturing.ttl artifacts/phase10-closure/manufacturing.owl'` | PASS | protege.txt; no interactive GUI assertion |
| Broker/provider configuration compatibility | `uv run python scripts/test_keycloak.py` | PASS | refreshed-keycloak.txt; actual pinned same-version supplier image, three dummy provider imports, local Code/PKCE and token checks |
| Ingress TLS/hosts/redirect/log privacy | `FOUNDRY_INGRESS_TEST_IMAGE=csh-foundry-ingress:phase10-closure uv run python scripts/test_ingress.py` | PASS | ingress-stable-test.txt; callback sentinel absent; no target DNS/certificate certification |
| Production Docker builds | `docker build` with api/studio/semantic/ingress Dockerfiles; semantic base explicitly selected | PASS | release-*-build.txt, ingress-stable-build.txt; image identities in scan inventories/runtime.json |
| Python dependency audit | `uv export --frozen --no-dev --no-emit-workspace`; pinned `pip-audit --disable-pip --no-deps` | PASS | python-audit.txt; production dependency scope |
| npm dependency audit | `npm audit --omit=dev --prefix apps/studio --json` | PASS | npm-audit.json; production dependency scope |
| App/semantic image SBOM and scans | `uv run python scripts/scan_images.py` on final app images | FAIL gate; PASS SBOM | release-scans.txt; 60/59/60 high matches, zero critical in those three images |
| Infrastructure scans/remediation | Same scanner on actual PG/Keycloak/ingress images before and after changes | FAIL retained gates | Infrastructure baseline/refreshed/final inventories; final stable ingress PASS 0 high/critical; supplier PostgreSQL/Keycloak criticals remain; no suppression |
| Combined deployment / manufacturing / workers / sessions / security / rotations / rollback | `uv run python scripts/accept_phase10.py` using actual production profile/images | PASS stated checks | deployment.json and acceptance-stable.txt (34 PASS assertions / 32 distinct checks). Individual missing scenarios remain NOT RUN, not implied PASS |
| Local physical/WAL/PITR | `uv run python scripts/test_recovery.py` | PASS | recovery.txt; isolated PG 17.6 drill, not combined-profile 17.11 PITR or off-host DR |
| Combined encrypted logical recovery | Acceptance runner dump → age → new restore DB → 21 table checksums | PASS | deployment.json; encrypted backup and keys remain private; no serving DB overwrite |
| Actual container isolation | Runtime cgroup/read-only/tmpfs/nonroot/egress assertions | PASS | runtime.json; deployment.json; supervisor still needs internal networks |
| Real local alert firing/delivery/resolution | `uv run python scripts/test_alert_delivery.py` | PASS | alerts-final.txt/json; synthetic scrape target, unchanged 2-minute rule, disposable receiver |
| Load sample | Acceptance runner at 1/4/8 clients, 20s each | PASS execution / provisional targets evaluated separately | deployed-load.json and load-summary.json; contended sample retained; no capacity/SLO certification |
| Promotion rejection and evidence integrity | `uv run pytest -q services/api/tests/test_production_profile.py services/api/tests/test_release_evidence.py`; missing-manifest CLI | PASS negative checks | closure-tests-final.txt (4 tests); promotion-negative.txt intentionally exits nonzero |
| Live Microsoft/Google/Workspace SSO | Requires approved external registrations/organizations/consent/test users/verified links | NOT RUN | No external credentials/approvals supplied; configuration import is not federation certification |
| Off-host disaster recovery / production custody | Owner-led encrypted off-host restore with protected keys and target | NOT RUN | No approved destination, custody/retention/owner/recovery host |
| Production monitoring / receiver | Actual target scrape/host/WAL/worker/backup probes and approved on-call receiver | NOT RUN | Local rule mechanics alone do not satisfy this gate |
| Hosted CI/provenance/reviewers/retention | Authorized hosted workflow/attestation verification | NOT RUN | Local changes not promoted; no hosted reviewer or protection configuration modified |
| Full sustained capacity and comprehensive deployed fault matrix | Target hardware/data/SLOs; remaining signing/JWKS/outbox/artifact/concurrency/queued/executing failures | NOT RUN | Scoped regression/fault checks are separately recorded; no full-matrix success claimed |
| Browser OIDC client-secret rotation | Studio is a public S256-PKCE client | NOT SUPPORTED | No browser client secret exists |
| Individual SDK artifact signatures/signing-key rotation | Signing not implemented | NOT SUPPORTED | Digests/manifests do not imply signatures |
| Local backup-recipient rotation | Reencrypt the tested backup in memory to a new recipient; verify both payload hashes, old-key rejection for new ciphertext and historical readability | PASS | backup-rotation.json; private keys/ciphertexts retained |
| Production backup-key custody and host-loss recovery | Separate owner/key-custody drill | NOT RUN | Local recipient mechanics do not prove custody/retention/disaster recovery |

Intermediate failures remain in baseline/browser/deployment/alert/ingress logs. Deployment scripts
write sensitive diagnostics and generated secrets only beneath the private path referenced by each
redacted result; do not publish those `artifacts/` directories. A run interrupted while its Compose
input was being edited is not evidence of a password-rotation defect or a passing full run. The
final immutable selected configuration is rerun separately. Alert harness failures were traced to
an invalid synthetic metrics response content type; production alert expressions/durations were not
weakened. Ingress package experiments exposed a template-directory mismatch; final supplier stable
image preserves the official layout. Earlier scanner matches/results are not erased.

Local/production-like/production acceptance remain BLOCKED. Container findings require remediation
or explicitly authorized owner dispositions, and remaining local/target/external requirements are
not silently deferred to Phase 11. See the final report and 23-category readiness matrix.

Final scoped performance: 260 requests, zero errors; final per-operation engineering targets PASS,
with p95 at eight clients up to 343.183 ms for reads/preview/traversal and 359.103 ms for SDK generation.
`load-summary.json` is derived from the SHA256-bound raw samples. Earlier contended targets FAIL and
remain preserved. Final measurements resolve the fixed Docker port before timing each HTTP request;
no control-plane subprocess lookup is included in the timed request. Full capacity certification
and sustained all-operation resource/queue distributions remain NOT RUN.
