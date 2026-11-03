# Artifact storage configuration and operations

Phase 12 only. Production remains BLOCKED under PLANS.md Section 23B. No deployment is authorized.
Storage is optional: with FOUNDRY_ARTIFACT_BACKEND=disabled (default), ontology and Projects work
without object storage, while artifact creation/transfers return storage_disabled. Database migration
is still required for the application revision. Never run migrations against shared developer data
without the operator's separate instruction; use the isolated validation script below.

## Configuration

All variables use `FOUNDRY_ARTIFACT_`. Settings validate at app creation. Secrets support the existing
FOUNDRY_SECRETS_DIRECTORY injection (filenames use the full artifact prefix), environment variables,
or the boto3 credential chain (workload identity / AWS shared credential providers). Keep credentials
out of source control, browser bundles, command output and ConfigMaps. No client can select these.

| Suffix | Default / constraints |
| --- | --- |
| BACKEND | disabled or s3 |
| ENDPOINT | unset for AWS regional service; explicit trusted origin for compatible providers; no userinfo/path/query/fragment |
| REGION | us-east-1 |
| BUCKET | foundry-artifacts, explicit S3 bucket name |
| ADDRESSING | path or virtual |
| ACCESS_KEY / SECRET_KEY | both or neither (SDK credential chain); optional session token via AWS_SESSION_TOKEN |
| CA_BUNDLE | optional readable trusted CA file; otherwise system trust; TLS verification always enabled |
| DEVELOPMENT_HTTP | false; explicitly true only for development internal HTTP; rejected for enabled production storage |
| CLIENT_REACHABLE | false; explicitly enable only for client-reachable HTTPS endpoints |
| PRESIGN_SECONDS | 60, range 1–300, GET only |
| MAX_BYTES | 67108864, range 1–1073741824; Studio/BFF ceiling stays 64 MiB |
| PART_BYTES | 8388608, range 5242880–67108864; multipart above this threshold |
| CONNECT_SECONDS | 3, range 1–10 |
| READ_SECONDS | 10, range 1–30 |
| ATTEMPTS | 3 total, range 1–5, standard bounded SDK retry mode |
| ABANDONED_SECONDS | 86400, range 3600–2592000; explicit owner cleanup, no committed purge |

Transport deadline is 60 seconds; Studio BFF upstream deadline 55 seconds. Storage timeouts bound
individual calls, not total SDK multipart elapsed time. Uploads near limits require appropriate
latency/bandwidth. A timed-out worker thread may finish a storage operation after HTTP cancellation;
metadata remains governed by its transaction and initiation record. Follow up by reading state.
Disk capacity must accommodate concurrent transfers up to MAX_BYTES each. No capacity claim is made.
Changing bucket/backend is not a transparent migration: historical-version access fails closed on
configuration mismatch. Plan and verify a separate storage migration rather than changing identities.

## Opt-in local MinIO

Base Compose publishes no MinIO ports. The startup wrapper refuses missing root credentials
before launching MinIO, preventing upstream development defaults. Supply ignored local `.env` or exported environment variables:
MINIO_ROOT_USER, MINIO_ROOT_PASSWORD, MINIO_APP_USER, MINIO_APP_PASSWORD. Generate strong distinct
bootstrap/application values with a local secret manager; no sample passwords are committed. Keep
POSTGRES_PASSWORD as required by the pre-existing Compose workflow. Do not pass secrets on CLI flags.

```sh
docker compose --env-file .env -f infrastructure/compose.yaml --profile minio up -d --wait minio
docker compose --env-file .env -f infrastructure/compose.yaml --profile minio run --rm minio-init
```

The initializer is safe to repeat: creates foundry-artifacts/foundry-datasets/foundry-media if missing,
reconciles the generic-artifact policy and separate application user, and never deletes buckets or
objects. Only foundry-artifacts is accessible to the API identity; future buckets receive no app
permissions. API access allows get/put/delete/abort/list multipart and bucket listing needed for
unambiguous missing-object HEAD responses. Bucket ownership/bootstrap operations remain admin-only.
Do not assign this dedicated application identity unrelated policies. No s3:* grant or anonymous
policy is installed. Restart preserves the named minio-data volume. Init failures stop initialization;
run it successfully before enabling storage. The API has no mandatory MinIO depends_on edge.

For Compose API set FOUNDRY_ARTIFACT_BACKEND=s3. The internal default is http://minio:9000 with
explicit development HTTP. For an API running on the host, optionally add
`-f infrastructure/minio/localhost.yaml` and use http://127.0.0.1:9000; ports are loopback only and
configurable with MINIO_API_PORT / MINIO_CONSOLE_PORT. No public exposure or disabled TLS validation.
Stop services with `down` **without --volumes** to keep bytes. Never remove shared developer volumes.
Intentional cleanup of an independently named disposable test project belongs to its test runner.

Server digest: minio/minio@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e
(RELEASE.2025-09-07T16-13-09Z). Client digest:
minio/mc@sha256:a7fe349ef4bd8521fb8497f55c6042871b2ae640607cf99d9bede5e9bdf11727
(RELEASE.2025-08-13T08-35-41Z). Verified through actual `--version` invocations and real local tests.
These are cached upstream images, not production-certified images. During implementation upstream
Docker Hub pulls were denied and Quay pulls returned 401; legacy binary downloads returned 410.
A fresh host needs a trusted archive/mirror of these exact images (docker load preserves digests)
or a separately reviewed, explicitly pinned replacement. No floating tag or silent substitute is
used. Availability on a fresh host and architectures other than tested arm64 are NOT RUN.

## External S3 / OKD4 operator contract

Use externally managed storage; MinIO is not required in OKD4. Prepare a private bucket and scoped
workload credentials outside the application. Inject the variables above via the deployment's
existing ConfigMap/Secret conventions: FOUNDRY_ARTIFACT_BACKEND=s3, ENDPOINT=https://<trusted-host>,
BUCKET=<private-bucket>, REGION=<provider-region>, ADDRESSING=path (or virtual). Leave
DEVELOPMENT_HTTP=false and CLIENT_REACHABLE=false. Mount provider CA trust read-only if private;
never use insecure TLS flags. AWS default endpoints can use workload credential providers instead
of static keys. Validate credential discovery for the actual deployment before release.

Permit DNS and egress to the provider's approved HTTPS addresses/port in the existing NetworkPolicy
and organizational firewall. Private endpoints remain internal; browser traffic goes through Studio
and FastAPI. Inject secrets only into the API workload; no root credentials in API/worker/Studio.
No organizational resources have been created or modified. Default server-side encryption, backup,
object lock/versioning, access logging and IAM policies are provider/operator responsibilities.
Conditional writes (PutObject and CompleteMultipartUpload If-None-Match) are required: providers
without them are unsupported, never silently downgraded to overwrite. Read-after-write consistency
must support verification. Test provider compatibility in an isolated approved bucket before use.

Back up PostgreSQL and bytes together. Retain every committed key, including archived resources;
restore bytes first and reconcile immutable metadata checksums before exposing downloads. Restoring
only PostgreSQL is insufficient. Never enable prefix expiration or out-of-band removal for committed
keys. Off-host backups, disaster recovery, encryption/key rotation and organizational certification
remain mandatory Section 23B work; this development validation does not certify production.

## Reproducible validation

`uv run python scripts/validate_phase12.py --full --browser` creates a random Compose project with
fresh credentials, loopback-only random port, disposable MinIO volume and isolated PostgreSQL schemas.
It repeats initialization, writes a sentinel, restarts MinIO and verifies persistence, runs drift and
Python regressions, and optionally the real authenticated browser suite. It removes only its own
Compose resources. PostgreSQL connection comes from TEST_DATABASE_URL or existing local settings;
the shared schema and Alembic revision are never upgraded. Requires cached pinned images, Docker,
PostgreSQL, the pinned semantic binary, Node >=22 and Playwright browser dependencies.

The SDK contract follows the installed botocore model, including conditional multipart completion;
see [boto3 PutObject](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html)
and [CompleteMultipartUpload](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/complete_multipart_upload.html).
