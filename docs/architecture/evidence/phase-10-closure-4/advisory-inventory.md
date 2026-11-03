# Closure 4 advisory review — 2026-11-03

All raw matches remain blocking. REMEDIATED below identifies a supported system-CA update already present, not a new image patch or authorized exception.

| Advisory | Severity | Technical status | Backport / vendor result |
|---|---|---|---|
| CVE-2025-69720 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-102010 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-107161 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-107778 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-119373 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-119374 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-119379 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-119586 | High | UNFIXED | No supplier fixed sqlite-libs version identified in selected UBI9 broker |
| CVE-2026-19499 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-24882 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-5435 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-54369 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-54370 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-6653 | Critical | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-74860 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-76642 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-78408 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-78409 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-78410 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-82560 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-84243 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-85091 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-86138 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-86139 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-86140 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-86142 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-86143 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-86144 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-91403 | Critical | REMEDIATED | System ca-certificates 2026.2.92_v9.0.319-90.3.el9_8 equals Red Hat RHSA-2026:88459 corrective package; both implicated root subjects absent in actual default Java store |
| CVE-2026-9538 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| CVE-2026-95619 | High | UNFIXED | No supported trixie fix identified in current vendor snapshot; no scanner exemption |
| GHSA-xxph-c9ww-hj94 | High | UNFIXED | Guava 33.7.2 fixes upstream; current maintained Keycloak 26.8.1 bundles 33.6.0-jre |

Installed versions, image roles, fix versions, origin, residual exposure and unassigned approval roles are retained in distinct-advisories.json and the complete per-match vulnerability-disposition.json. Snapshots are in vendor/. PostgreSQL supported-package upgrade simulation offers only tzdata. No affected essential library is force-purged. All scan/SBOM results are from the final selected six image identities. No new package vulnerability has been patched by Closure 4.
