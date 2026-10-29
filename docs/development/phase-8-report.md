# Phase 8 report — Native Ontology Manager and Ontology Studio

PHASE: **8 only**, 2026-10-29, America/New_York.
Base Git revision: `b77ad7ca589fc8d1ba26e01bc4766087f2c842f7`.
STATUS: **Implemented and validated within the supported developer-facing scope below.**
Changes remain uncommitted. No external deployment, live Microsoft/Google integration, Phase 9
branching/SDK implementation or Phase 10 hardening was performed.

## Functionality implemented

- One strict TypeScript Next.js/React application with shared tenant/ontology shell, separate Manager
  and Studio navigation, loading/error/empty states, responsive layouts, explicit form labels,
  keyboard controls, skip navigation and schema graph textual relationship equivalents.
- Provider-independent Authorization Code + PKCE S256 login. Server verifies signed ID and API access
  tokens separately, including nonce, issuer/audience/expiry, identity/client and RFC 9068 access-token
  profile. Single-use browser-bound state, fixed callback, same-origin trusted provider metadata,
  bounded I/O, opaque HttpOnly cookies, HTTPS Secure cookies, Origin/CSRF checks, expiry and logout.
  Access tokens remain in the Next server; no refresh or browser token persistence.
- Identity-scoped tenant discovery before selection; selected membership verified through existing
  `/security/me`. Permission-aware controls remain advisory; FastAPI independently verifies bearer
  tokens and rechecks current membership/RBAC/ABAC, revocation and transaction authority.
- Fixed-origin BFF restricted by actual OpenAPI methods/routes. Encoded path separators/dot segments,
  arbitrary upstream URLs, redirects, unexpected query keys and caller auth headers are rejected.
  Request size 64 KiB, response size 5 MiB, finite upstream deadlines, no-store responses and sanitized
  error codes. Each request binds the expected selected tenant; queued requests fail rather than
  applying against a newly selected tenant. Stale ontology-list responses are discarded after switches.
- Manager: ontology creation, native graph/type/property/relationship editing, canonical property
  constraints, declarative action authoring, explicit draft saves, new-version drafts, paged version
  history/hashes/publish attribution, unsaved-change warnings, backend compatibility validation,
  separate publication and activation, and explicit migration-plan creation/approval workflows.
- Optional expected_hash saves compare canonical draft hashes under the existing ontology write lock;
  stale editors receive HTTP 412 before mutation. Published immutability remains unchanged.
- Turtle/RDF/XML file loading, explicit mapping/conflict request editors, independent import preview
  and draft creation, original/vocabulary/diagnostic inspection, published OWL export and downloads.
- Studio: bounded typed object query builder, projections/sorting/filtering, cursor pages, forward/
  inverse traversal, advanced query AST, ephemeral named Object Sets and object detail inspection.
  Additional developer forms cover aggregates, object/link changes and execution/audit reads.
- Action parameter forms from canonical definitions, advisory previews, explicit execution approval,
  stable idempotency keys for retries, preview invalidation when parameters change and history.
- Ingestion source/mapping publication and run submission/inspection/diagnostics/cancellation.
  Semantic compilation/native artifacts/authorized exports, validation/reasoning/change submission,
  cancellation, report/proof/derived artifact inspection, facts/provenance/freshness and approvals.
  Job dashboards show page-scoped status counts/progress and semantic output inspection.
- Actual OpenAPI export and generated application TypeScript contracts, exact npm pins/lockfile,
  frontend unit/route/component tests, signed local TLS OIDC browser tests, Docker development
  integration, non-root standalone Studio image, CI checks and Phase 9 preparation documentation.

Complex action declarations, migration updates, OWL mappings and ingestion/semantic request contracts
use labeled JSON editors with concrete templates. Object/property/link authoring, query construction,
action parameter entry and execution review use dedicated controls. Backend services own validation,
compatibility, authorization, transactions, transformations and reasoning; there is no parallel engine.

## Files created or modified

| Area | Files |
|---|---|
| New Studio application | `apps/studio/app/{layout,page,loading,error}.tsx`, `app/style.css`, `app/auth/[operation]/route.ts`, `app/bff/route.ts` |
| Shared UI | `apps/studio/components/{workspace,ui,schema-graph}.tsx` |
| Workspace features | `apps/studio/features/{manager,explorer,operations,job-dashboard}.tsx` |
| Integration and auth | `apps/studio/lib/{api,server}.ts`, generated `lib/openapi.json`, `lib/api-schema.ts` |
| Frontend configuration | `apps/studio/{package.json,package-lock.json,tsconfig.json,next-env.d.ts,next.config.ts,vitest.config.ts,playwright.config.ts}` |
| Frontend tests | `apps/studio/tests/{security.test.ts,routes.test.ts,ui.test.tsx,e2e_backend.py,oidc_transport.mjs,e2e/workflow.spec.ts}` |
| New backend tests | `services/api/tests/test_studio.py` |
| Backend extensions | `services/api/src/ontology_platform/{dependencies.py,api/v1/routes.py,metadata/service.py,security/identity.py,security/routes.py}` |
| Tooling | New `scripts/{export_openapi,test_studio,smoke_studio_container}.py`; existing `smoke_security_container.py` now accepts image/evidence overrides with original defaults retained |
| Development/containers/CI | `infrastructure/docker/studio.Dockerfile`, `infrastructure/compose.yaml`, `.dockerignore`, `.gitignore`, `.env.example`, `.github/workflows/ci.yaml` |
| Documentation | Root and Studio READMEs, `docs/api/{README,security}.md`, ADR `0029-browser-session-and-studio.md`, Phase 8 checklist/report and `phase-9-preparation.md` |
| Next-generated guidance | `apps/studio/AGENTS.md` is generated by pinned Next dev; bundled route-handler/cookie/environment guides were checked |
| Evidence | `docs/architecture/evidence/phase-8/` baseline/final regression, frontend tests/build/checks, container builds/smokes, OWLAPI and integrity files |

No canonical fixture, root AGENTS.md, PLANS.md, Python lockfile, upstream engine/parser version,
canonical Pydantic schema or existing test was weakened, removed or rewritten. Earlier phase evidence
is preserved. The old Phase 7 report described uncommitted Phase 6/7 work; the arrival tree was clean
and that implementation was already in the base revision. No prior changes were discarded.

## Database migrations

**None.** PostgreSQL remains at **0013_security**. Membership discovery uses existing identity,
principal, membership and tenant tables. Draft CAS uses the existing canonical hash and ontology lock.
Session state is transient in the single Next process, not another operational store or registry.

## Baseline, environment and executed validation

`uv sync --frozen`: PASS. `alembic current`: 0013_security (head). Complete configured baseline:
**461 passed, 1 strict expected failure, zero skips, 245.45s**. All existing security, import and
semantic tests ran as part of that baseline, before the new suite was counted.

Environment: macOS ARM64; Python **3.12.0**; PostgreSQL **17.6**; Open Ontologies **2.1.0**;
RDFLib **7.1.4**; pySHACL **0.30.1**; OWLAPI **4.5.29**; PyJWT **2.15.0**; Node **24.22.1**.
Studio pins Next **16.4.3**, React **19.3.1**, TypeScript **5.9.3**, jose **6.2.14**,
Vitest **5.0.5**, Playwright **1.64.1**. See package-lock and `integrity.json` for exact inputs.
The host default Node 16 was not used. Host npm 7 emitted dependency-engine/deprecation warnings;
Node 24 container builds use the bundled npm. These warnings did not prevent executed checks.

| Check | Result | Evidence / scope |
|---|---|---|
| Complete configured Python regression | **PASS** | `validation-final.txt`: **464 passed, 1 xfailed, zero skips, 244.75s** |
| Ruff lint/format, strict mypy, Alembic drift | **PASS** | Regression preamble; `final-checks.txt`; 83 application/schema modules, 140 Python files formatted |
| Frontend formatting / strict typecheck | **PASS** | `frontend-checks.txt` |
| Frontend unit/route/component tests | **PASS** | `frontend-tests.txt`: **24 passed** across 3 files |
| Production Next build | **PASS** | `frontend-build.txt`; app, dynamic auth and BFF routes compile |
| Signed browser E2E | **PASS** | `e2e.txt`: **3 passed**, actual TLS local IdP, real FastAPI/PostgreSQL and delegated workers |
| Browser manufacturing reference workflow | **PASS** | Publish/activate; source/mapping configuration; 63 ingested objects; 20 machines / 3 critical; traversal; governed action; completed semantic validation job |
| Browser native authoring / OWL / isolation | **PASS** | Create native type/property/link; save/validate; import preview/vocabulary; tenant switch removes prior ontology; missing session returns sign-in |
| Authentication/CSRF/proxy/tenant-switch defenses | **PASS** | Signed nonce/audience/profile/identity/expiry cases; state replay, forged session, CSRF, blocked paths, expected-tenant guard, sanitized errors, logout invalidation |
| Browser cookie/token exposure checks | **PASS** | HttpOnly opaque cookie; inaccessible through document.cookie; no localStorage data; access tokens only used server-to-API |
| Turtle parsing / CSV counts, keys, FKs / RDF consistency | **PASS** | Full unchanged fixture/Polars suite; exact hashes in `integrity.json` |
| Raw pySHACL conformance | **FAIL** | Preserved strict xfail: simple/xsd:string `sh:in` mismatch; never reported as raw PASS |
| Normalized SHACL / nine negative cases | **PASS** | Existing in-memory RDF 1.1 compatibility tests, unchanged fixtures |
| Pinned engine raw SHACL / CriticalMachine owl-rl-ext | **PASS** | Executed existing configured semantic suites |
| CriticalMachine under base owl-rl | **NOT SUPPORTED** | Existing explicitly tested profile limitation retained |
| Independent Lean proof checking | **NOT RUN** | No installed independent checker; generated certificates are not called verified proofs |
| PostgreSQL integration / FastAPI queries | **PASS** | Full real-database suite plus browser queries; draft CAS and membership tests |
| Actions / reconciliation / Polars ingestion | **PASS** | Existing complete suite and browser ingestion/action workflow |
| Authorization and tenant isolation | **PASS** | All Phase 7 regressions; new membership/disabled/selection checks; browser tenant switch |
| Protégé supported file interchange / OWLAPI | **PASS** | Existing import suite; `protege.txt`: actual 4.5.29 RDF/XML round trip, known xsd:date declaration delta |
| Protégé desktop GUI / live WebProtégé | **NOT RUN** | Optional GUI/deployment unavailable/not requested; no GUI-authored claim |
| Studio final image build / smoke | **PASS** | `docker-build.txt`, `docker-smoke.txt`: root, headers, denial, unconfigured login failure, non-root runtime |
| API final image build / smoke | **PASS** | `api-docker-build.txt`, `api-docker-smoke*.txt`: readiness at 0013, Bearer OpenAPI, forged credentials denied, invalid OIDC configuration fails startup |
| Remote CI / public deployment / live provider SSO | **NOT RUN** | Workflow added locally; no push or deployment authorized/performed; live Microsoft/Google deferred |

The local E2E provider uses generated short-lived TLS/signing material and immutable issuer identity.
Test-only Node/Python/browser transports remap its fixed issuer socket to 8443 because this host cannot
bind port 443. The provider still performs single-use code/PKCE checks, and the actual Phase 7 verifier
validates signed RFC 9068 tokens through trusted TLS. Production issuer rules are unchanged. The test
signing key is removed at exit. All fixture data uses disposable PostgreSQL schemas; operational tenant
data is not used. Browser traces/screenshots stay under ignored artifacts/test-results.

Intermediate browser failures were corrected: CSP form redirect interaction, select labeling, test
transport redirect-following, asynchronous test locators and a sidebar sizing issue. A missing
fixture flush was fixed in the new membership test. The final evidence above, rather than partial
runs, is the passing result. No unexpected final failure remains.

## Architectural decisions and known limitations

ADR 0029 documents browser/session and UI boundaries. PostgreSQL remains authoritative; Next receives
no database credential. Existing canonical/RDF boundaries, server connector registrations, worker
service delegation, publication/activation and backend governance remain intact.

1. **Single Next process/replica.** Process-local stores cap sessions and pending logins at 1,000 each;
   sessions disappear on restart. No refresh-token persistence, horizontal session store, broker-wide
   logout, automatic account linking or live Microsoft/Google SSO. Register the documented public
   PKCE client with a compatible broker; unconfigured authentication fails closed.
2. HTTP cookies are allowed only for loopback development origins. Future public deployment needs
   HTTPS, reviewed proxy/network/admission settings and operational hardening. CSP allows Next inline
   bootstrap/styles; per-request nonce CSP is a documented further hardening opportunity. Production
   unsafe-eval is excluded. Production deployment was not performed.
3. Authoring is single-user editing with hash collision protection, not collaboration/branching.
   Graph layout is deterministic and type selection is available through labeled controls; it is not
   a full drag-and-drop ontology diagramming system. Canonical Pydantic constraints remain authoritative.
4. Complex declarative contracts use JSON editors. Object Sets are transient query definitions and
   are lost when their explorer component closes; no saved-set persistence API exists. No generic SDK,
   query optimizer, client authorization engine or frontend semantic reasoner was implemented.
5. Job dashboards show bounded pages and explicit refresh. Jobs need separately configured authorized
   workers; browser submission is not completion. Scheduling, hard resource isolation, large imports
   and aggregate storage quotas remain backend/deployment limitations documented in earlier phases.
6. OWL import records are inspected by returned identifier; there is no invented collection/history
   endpoint. Only the existing Turtle/RDF/XML subset and explicit mappings are supported. Preview,
   CREATE_DRAFT, publish and activate remain distinct. Diagnostics and original semantic content are
   preserved; no implicit operational action/access policy is inferred.
7. Existing raw pySHACL mismatch, base owl-rl limitation, unverified proof certificates, schema-activation
   size bounds, coarse locks and private/freshness-governed semantic results remain unchanged.
8. Browser E2E ran in Chromium against the development server; production builds and final-image
   unauthenticated/security smoke were executed separately. Full signed login inside the final Docker
   image, other browsers, formal screen-reader auditing and external IdP deployments were not run.

## Next recommended phase

Stop after Phase 8. Review this developer application and its stated limits, then separately approve
**Phase 9 — Branching and SDK generation** if desired. `phase-9-preparation.md` records contracts and
invariants for that review only. Live Microsoft/Google broker integration remains Phase 10.
