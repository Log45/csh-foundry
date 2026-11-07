# Development object storage

Use the existing optional MinIO Compose services, digest-pinned images, persistent `minio-data` volume,
`infrastructure/minio/init.sh`, bucket policy and S3ArtifactStore. API and worker inherit identical
server-side `FOUNDRY_ARTIFACT_*` settings: backend `s3`, endpoint `http://minio:9000`, development HTTP
explicitly enabled, bucket `foundry-artifacts`, region `us-east-1`, addressing `path`, and application
access/secret keys. MinIO root credentials are used only by bootstrap; they never enter Studio.

The Phase 21 rollout helper stores private credentials in ignored mode-0600 artifacts and reuses them.
Repeat storage initialization does not remove buckets or objects. Preserve existing volumes. No
production credentials, public bucket, anonymous download, browser presigned HTTP capability or second
artifact store is introduced. Upload, immutable version, checksum, staging and publication contracts
remain those of Phases 12–20. Private DAG objects have no committed dataset resource capability.

Use targeted storage operations after topology inspection, never `compose down`, volume pruning or
cluster reset. API/worker/Studio recreation uses `--no-deps`; it does not restart PostgreSQL/Keycloak.
