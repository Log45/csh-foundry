# ADR 0045: General DAG execution and atomic output publication

Date: 2026-11-06. Status: implemented; locally accepted with validation and limits in the Phase 20 report.

Reconnaissance: Phase 14's Definition selects the first input and applies ordered steps. Binary
operations resolve only named raw inputs. ExecutionWorker owns one output reservation and commits
one physical/logical version and parent success. Phase 18's compiler follows the primary chain,
rejecting transformed fan-out and transformed right inputs. Phase 19 applications are independent.
Repository head is 0025_applications; staged Phase 19 work must be preserved.

Add a distinct closed format_version=2 definition alongside unchanged historical Definition JSON.
Stable named inputs, transformation IDs, explicit input/right ports and named output declarations
are independent of canvas positions. Deterministic Kahn ordering and canonical sorted serialization
supply plan identities. The existing Polars operation planner remains the semantic authority.

Extend ExecutionWorker, not the scheduler: one parent job, sequential bounded isolated node children,
immutable run plan and fenced node records. Materialize each transformation once to Parquet, keep
private run-scoped immutable storage for verified recovery, and reuse scans for all consumers.
A replacement worker verifies checksums and exact plan/input identities before reuse.

Prepare output bytes at final immutable ObjectKey identities without creating discoverable artifact
or dataset metadata. A durable private manifest pins output identities/checksums/schema/targets.
Under existing tenant/security locking, acquire target locks in sorted order, reauthorize every
input/output and check fencing/cancellation/deadline. A single PostgreSQL transaction creates every
physical/logical version through DatasetService, completes the manifest and marks parent success.
No post-commit object move, partial publication, or S3/PostgreSQL distributed ACID claim. Existing
targets append immutable versions serialized by governed locks; new resources belong to commit.
Committed parent state resolves ambiguous acknowledgement; retries cannot publish twice.

Development API depends on PostgreSQL; Studio depends on API. The separately running protected
foundry-keycloak and foundry-keycloak-tls containers are not targets of any Compose operation.
Never restart shared PostgreSQL until its Keycloak dependency has been ruled out; tests only create
owned disposable schemas and private MinIO Compose projects. No shared migration or reset.

No arbitrary code, Spark, Rust, new scheduler/database, or production certification. §23B BLOCKED.
