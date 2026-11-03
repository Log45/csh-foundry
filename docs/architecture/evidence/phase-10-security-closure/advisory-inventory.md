# Advisory engineering review — 2026-11-03

All 32 baseline advisories reviewed. Classifications do not grant release approval. No risk exception is authorized.

| Advisory | Severity | Candidate classification | Current matches |
|---|---|---|---:|
| CVE-2025-69720 | High | VENDOR_DEPENDENT | 15 |
| CVE-2026-102010 | High | VENDOR_DEPENDENT | 12 |
| CVE-2026-107161 | High | VENDOR_DEPENDENT | 2 |
| CVE-2026-107778 | High | VENDOR_DEPENDENT | 4 |
| CVE-2026-119373 | High | VENDOR_DEPENDENT | 5 |
| CVE-2026-119374 | High | VENDOR_DEPENDENT | 4 |
| CVE-2026-119379 | High | VENDOR_DEPENDENT | 4 |
| CVE-2026-119586 | High | REQUIRES_REVIEW | 1 |
| CVE-2026-19499 | High | VENDOR_DEPENDENT | 10 |
| CVE-2026-24882 | High | ALREADY_REMEDIATED | 0 |
| CVE-2026-5435 | High | VENDOR_DEPENDENT | 10 |
| CVE-2026-54369 | High | VENDOR_DEPENDENT | 4 |
| CVE-2026-54370 | High | VENDOR_DEPENDENT | 4 |
| CVE-2026-6653 | Critical | VENDOR_DEPENDENT | 1 |
| CVE-2026-74860 | High | VENDOR_DEPENDENT | 1 |
| CVE-2026-76642 | High | VENDOR_DEPENDENT | 36 |
| CVE-2026-78408 | High | VENDOR_DEPENDENT | 36 |
| CVE-2026-78409 | High | VENDOR_DEPENDENT | 36 |
| CVE-2026-78410 | High | VENDOR_DEPENDENT | 36 |
| CVE-2026-82560 | High | VENDOR_DEPENDENT | 7 |
| CVE-2026-84243 | High | VENDOR_DEPENDENT | 10 |
| CVE-2026-85091 | High | VENDOR_DEPENDENT | 4 |
| CVE-2026-86138 | High | VENDOR_DEPENDENT | 1 |
| CVE-2026-86139 | High | VENDOR_DEPENDENT | 1 |
| CVE-2026-86140 | High | VENDOR_DEPENDENT | 1 |
| CVE-2026-86142 | High | VENDOR_DEPENDENT | 1 |
| CVE-2026-86143 | High | VENDOR_DEPENDENT | 1 |
| CVE-2026-86144 | High | VENDOR_DEPENDENT | 1 |
| CVE-2026-91403 | Critical | ALREADY_REMEDIATED | 1 |
| CVE-2026-9538 | High | VENDOR_DEPENDENT | 7 |
| CVE-2026-95619 | High | VENDOR_DEPENDENT | 12 |
| GHSA-xxph-c9ww-hj94 | High | VENDOR_DEPENDENT | 1 |

Complete versions, package identities, vendor snapshots, exposure, removal/upgrade blockers, exact image/scan/SBOM bindings, unassigned approval authority and November 10 review trigger are in `advisory-remediation-matrix.json`.

CVE-2026-24882: all GnuPG source-package matches removed using apt; this is toolchain removal, not a patch of TPM code or proof it was exposed previously. CVE-2026-91403: CA remediation already present; raw critical match requires independent review. All other retained matches remain blocking.
