#!/bin/bash
set -euo pipefail
export KC_DB_PASSWORD="$(cat /run/secrets/keycloak_password)"
export KC_BOOTSTRAP_ADMIN_PASSWORD="$(cat /run/secrets/keycloak_admin_password)"
export WORKER_CLIENT_SECRET="$(cat /run/secrets/FOUNDRY_WORKER_CLIENT_SECRET)"
# Optional upstream secrets are provided as separate mounted files by the operator.
for name in ENTRA_CLIENT_SECRET GOOGLE_CLIENT_SECRET WORKSPACE_CLIENT_SECRET; do
  if [ -f "/run/secrets/$name" ]; then export "$name=$(cat "/run/secrets/$name")"; fi
done
exec /opt/keycloak/bin/kc.sh start --import-realm
