# Phase 10 security remediation — 2026-11-03

**Implementation PASS; local acceptance BLOCKED; production-like acceptance BLOCKED;
production certification NOT RUN. Release gate BLOCKED. No risk exception authorized.**
Phase 11 remains unapproved. No migration; head remains `0017_capacity`.

Starting revision: `6ae76602bc329ed212a09970787f65354caeb585`, clean working tree
(`baseline.json`). Existing developer containers/data/realm/keys/trust/backups and all prior evidence
are preserved. Historical checksum verification passes 109/36/151/156 files in closures 1–4.
Generated secrets, private logs, backups and WAL stay under ignored `artifacts/`.

## Supported changes

- PostgreSQL derives from the same pinned official **17.11-trixie** index. Supported apt purge and
autoremove removes `gnupg`, `gnupg-l10n`, `gpg`, `gpg-agent`, `gpgconf`, `gpgsm`, `dirmngr` and unused
transitive helpers. These tools serve supplier build verification, not SQL/restore operations.
The exact removed package inventory is retained separately. PostgreSQL binaries, libxml2, Perl,
glibc, locales and extensions remain. Candidate apt/sqv signature verification still works.
- API uses the same pinned Python 3.12.16/trixie base in separate build/runtime stages. The runtime
copies the installed application without uv or its root cache. Semantic inherits that runtime;
pinned Open Ontologies 2.1.0 is unchanged. Nonroot imports and native engine startup pass.
- Studio retains its standalone multi-stage runtime and npm/Yarn removal; it also removes the
optional standalone mount command. API, semantic and PostgreSQL remove that command too.
No Python/Node/Rust application dependency high/critical match required a lockfile update.
Python and npm dependency audits pass without known vulnerabilities.
- Production requires explicit `POSTGRES_IMAGE` with a reviewed immutable digest. CI builds/scans/
archives the derived PostgreSQL image. This is a new public deployment configuration requirement;
existing developer Compose and databases are untouched. No image was published or promoted.

The original 179 application-image high matches share **eight OS source-package families and
18 advisory IDs**: util-linux, gcc-14, glibc, ncurses, sqlite3, perl, acl and zlib. The final
application subtotal is 167. `shared-vulnerability-sources.json` records SBOM ecosystems and
per-image counts. No high/critical Python/Node/Rust dependency match is reported; complete static
Rust dependency coverage is not inferred.

All 32 original advisories have engineering dossiers in `advisory-remediation-matrix.json`,
`critical-dispositions.json`, `high-dispositions.json` and `advisory-inventory.md`. Vendor snapshots
were freshly retrieved; raw reports remain unchanged. See `supported-upgrades.json` for every
selected/rejected/unavailable path and compatibility blocker. Essential-package force removal,
unstable libraries, unqualified libc/distribution changes and unsupported vendor JAR swaps were
rejected. SQLite removal is blocked by essential util-linux's liblastlog2 dependency (and Python's
native sqlite module); apt's failed simulation is retained.

## Before / after

| Role | Baseline high / critical | Candidate high / critical |
|---|---:|---:|
| API | 60 / 0 | 56 / 0 |
| Studio | 59 / 0 | 55 / 0 |
| Semantic | 60 / 0 | 56 / 0 |
| PostgreSQL | 92 / 1 | 81 / 1 |
| Keycloak | 3 / 1 | 3 / 1 |
| Ingress | 0 / 0 | 0 / 0 |
| Total | 274 / 2 | 251 / 2 |

Distinct high/critical IDs: **32 → 31**. Sixteen standalone mount source-package matches are also removed across four images, but the
four util-linux advisories remain in required libraries/packages. Seven GnuPG source-package matches for **CVE-2026-24882**
are removed by complete package/tool removal. This is not a code patch and does not prove the
baseline exposed the TPM daemon. No other advisory was newly remediated; no count-based dismissal.

**CVE-2026-6653 remains VENDOR_DEPENDENT/UNFIXED.** Fresh Debian tracker still lists installed
trixie libxml2 vulnerable; apt offers only tzdata, and official PostgreSQL 17 remains 17.11 at the
same index. libxml2 is dynamically linked by postgres and cannot be safely removed. XML parser
use-after-free requires crafted XML/entity handling; no arbitrary SQL/XML endpoint is offered,
but credentialed SQL/native parsing is reachable. Read-only apps, restricted database roles and
network isolation mitigate access, not the parser defect. No-DSA is not risk acceptance. An
independent security/release owner must require a supported fix or explicitly decide the exact
remaining risk. Revalidate on supplier/backport/image changes or by November 10.

**CVE-2026-91403 is technically ALREADY_REMEDIATED**, predating this iteration. Red Hat directs
RHEL OpenJDK to the corrected system CA package (CVE-2026-114406/RHSA-2026:88459), not an invented
Java-version fix. Installed CA package `2026.2.92_v9.0.319-90.3.el9_8` is bound to the unchanged
supplier SBOM/config identity. An independent fresh probe resolves Java trust to the system store,
records 118 subjects/fingerprints and verifies both implicated root subjects absent. See
`keycloak-trust-verification.json`. The scanner matches the Java RPM version; that critical match
is preserved. Recommend independent confirmation of the vendor-supported correction for this
exact image/package/scan. No named reviewer/approval exists. Custom stores and live upstream
federation remain separate verification duties; no scanner suppression is introduced.

Guava 33.7.2 is an upstream fix, but maintained Keycloak 26.8.1 still bundles 33.6.0-jre.
SQLite shell applicability requires independent review; an engineering observation is not VEX or
risk approval. Remaining advisories keep their complete image/package/evidence bindings and
unassigned required approver. Engineering classification counts: 29 vendor-dependent,
two already-remediated (one newly removed package toolchain, one existing CA fix), one requires review.

## Release policy

The existing CLI still rejects every raw high/critical finding and missing/non-PASS mandatory gate.
It now explicitly rejects disposition submissions because no independently administered advisory
approval provider exists. Hosted build provenance and the later production environment approval
are not advisory-risk authorization. No new trust root, local key-file option or self-exception
path is installed.

`scripts/security_dispositions.py` is a validation interface only. It requires exact advisory,
image/config, package name/version/purl and scan/SBOM/technical evidence hashes, explicit approved
decision/authority, timezone-aware validity dates, signer and detached signature. A separately
trusted external authorizer must verify both cryptography and authority. Test-only ephemeral
Ed25519 keys exercise the boundary; production supplies no authorizer. This interface does not
waive a finding, alter scanner output or enable promotion. Integration with an independently
approved trust provider remains unavailable pending organizational authorization.

Initial focused validation: **41 passed**; final security/release/recovery guards: **55 passed**, including no/missing/invalid signatures, unknown/self signer,
expired/future/naive dates, modified advisory/image/config/package/purl/evidence, unapproved decision,
wrong authority, reuse after image changes and missing SBOM/scan/candidate/deployment evidence.
The raw release CLI remains fail closed. Strict mypy passes both configured source (98 files) and
the new validation module separately. See `focused-tests.txt` and `release-policy-validation.json`.

## Candidate and validation

`images.json` records all six immutable selected identities. `supply-chain-binding.json` binds each
config digest, raw scan and CycloneDX bytes; all six identities/inventories PASS. Fresh builds and
scans/SBOMs executed for API, Studio, semantic and PostgreSQL. Keycloak and ingress raw scan/SBOMs
are reused only after confirming unchanged image, supplier index, database identity and historical
hashes. Their scan timestamps are retained; they are not relabeled as new executions. No identical
image/database scan was repeated. The same November 3 Grype database is valid. The initial 267-high candidate and its separate
combined run remain in `initial-*`; current identities/counts refer to the final mount-minimized candidate. Raw new evidence is
in ignored `artifacts/phase10-security-closure/scan/`; old raw bytes remain at their original paths.

Regression: **585 passed, one strict xfail, zero skips**; Ruff, formatting, strict mypy and Alembic
migration/drift PASS. Frontend **29 tests**, typecheck and production build PASS. Isolated durable
browser **five tests PASS**. Fixture Turtle/CSV/RDF/FK, normalized SHACL and negative cases,
real PostgreSQL queries/actions/ingestion/authorization/interchange and pinned semantic tests run
in the full configured regression. Raw pySHACL remains FAIL as a strict expected failure; base
owl-rl CriticalMachine inference remains NOT SUPPORTED. No assertions weakened.

Exact-candidate combined deployment: **PASS — 58 assertions / 50 distinct checks**, all PASS.
`combined/` binds all six final immutable IDs and includes actual Code/PKCE, API/Studio sessions,
tenant authorization, governed actions, ingestion crash/checkpoint recovery, semantic validation/
reasoning, both generated SDKs, branch governance, two-API races, quotas, restored application
startup after physical PITR, credential/signing-key rotation, TLS boundaries, rollback, two Studio
restarts/shared logout and real local alert delivery/resolution. All labeled disposable resources
are absent after cleanup. The preceding candidate also passed 58 assertions; it remains separately
identified in `initial-combined/` and is not substituted for final-candidate evidence.

The bounded final workload has **260 requests, zero errors**, read/preview operation p95 at most
273.150 ms and SDK p95 at most 271.997 ms. Existing provisional targets PASS; no new p99/max gate.
Final configured Python regression after all image changes: **585 passed / one strict xfail /
zero skips**, 318.32 s. Earlier 295.48 s execution remains in `pre-final-*`.

Final browser rerun: **five PASS**, unchanged assertions/timeouts. A preceding final browser attempt
had **four PASS / one FAIL**: the activation response reported `active_version: 1.0.0`, while the
header remained `No active schema`. That run occurred with concurrent regression; its cause is
**UNRESOLVED**, not attributed to the image changes or dismissed as harmless. Raw failure/trace
are retained in `browser-final-first-*` and ignored private storage. The final isolated execution
passes, but intermittent activation-display/refresh behavior remains a validation limitation.
No frontend application code or test assertion was changed to make the run pass.

Retained failed setup: an internal-only regression test network exposed no usable host port, causing
a migration connection failure. The corrected disposable project requires a real loopback-assigned
port before connecting. First native engine probe used unsupported `--version`; corrected `--help`
and later semantic integrations pass. Both original outputs are retained, not relabeled PASS.

Historical read/write acceptance remains valid at its stated scope. The unexplained historical
1,079 ms request is retained diagnostic evidence, **not an independent acceptance blocker** under
the current approved security scope. No new general latency/profiling investigation or invented
p99/max gate. Only the existing bounded combined workload is used for security regression.

## Remaining dependencies

Security gate FAIL and release gate BLOCKED until supported remaining fixes or independent,
cryptographically verifiable advisory-specific decisions exist. Exact candidate local deployment passes; this does not override security or certify an external target. Actual providers, off-host recovery/key custody,
production monitoring/on-call owners, target infrastructure/business SLOs and hosted approval/
provenance verification remain NOT RUN. No production certification or Phase 11 work is implied.

Aggregate regression acceptance remains **BLOCKED** pending review/remediation of the retained
intermittent activation-header failure; the five-pass isolated rerun does not erase it. The
release verifier rejects the actual candidate on container security, rejects deliberately forged
PASS summaries on the actual raw findings, and rejects a self-signed disposition because no
independent authorization provider exists (`release-gate-result.json`, `release-verifier.txt`).
