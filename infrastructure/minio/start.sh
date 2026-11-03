#!/bin/sh
set -eu
# Compose must remain usable with this profile disabled. Validate at service startup,
# before MinIO can fall back to any upstream development credentials.
: "${MINIO_ROOT_USER:?MINIO_ROOT_USER is required}"
: "${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD is required}"
exec minio "$@"
