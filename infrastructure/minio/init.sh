#!/bin/sh
set -eu
: "${MINIO_ROOT_USER:?required}" "${MINIO_ROOT_PASSWORD:?required}"
: "${MINIO_APP_USER:?required}" "${MINIO_APP_PASSWORD:?required}"
[ "$MINIO_ROOT_USER" != "$MINIO_APP_USER" ] || exit 1
# No shell tracing: credentials never enter logs or checked-in command strings.
mc alias set -- local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1 || {
  echo "MinIO bootstrap authentication failed" >&2; exit 1;
}
for bucket in foundry-artifacts foundry-datasets foundry-media; do
  mc mb --ignore-existing "local/$bucket"
done
mc admin policy create local foundry-artifacts /init/artifacts-policy.json
# User add is an idempotent credential reconciliation. No deletion of users, buckets or bytes.
mc admin user add -- local "$MINIO_APP_USER" "$MINIO_APP_PASSWORD" >/dev/null 2>&1 || {
  echo "MinIO application credential reconciliation failed" >&2; exit 1;
}
mc admin policy attach local foundry-artifacts --user="$MINIO_APP_USER" >/dev/null 2>&1 || {
  echo "MinIO application policy reconciliation failed" >&2; exit 1;
}
