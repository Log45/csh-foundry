"""Read-only production preflight. Supply the public environment file through the shell."""

import os
import re
import stat
from pathlib import Path


def main() -> None:
    for name in ("STUDIO_HOST", "API_HOST", "IDENTITY_HOST"):
        value = os.environ.get(name, "")
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", value) or "." not in value:
            raise SystemExit("FAIL explicit lowercase DNS host required: " + name)
        if "localhost" in value or value.endswith(".test"):
            raise SystemExit("FAIL production DNS required: " + name)
    for name in ("API_IMAGE", "STUDIO_IMAGE", "SEMANTIC_IMAGE", "INGRESS_IMAGE", "POSTGRES_IMAGE"):
        if not re.fullmatch(r"[a-z0-9./_-]+@sha256:[0-9a-f]{64}", os.environ.get(name, "")):
            raise SystemExit("FAIL approved immutable image digest required: " + name)
    root = Path(os.environ["SECRETS_DIRECTORY"])
    for name in (
        "postgres_password",
        "migrator_password",
        "runtime_password",
        "keycloak_password",
        "keycloak_admin_password",
        "FOUNDRY_DATABASE_URL",
        "FOUNDRY_BROWSER_STATE_SECRET",
        "FOUNDRY_BROWSER_STATE_KEYS",
        "FOUNDRY_QUERY_CURSOR_SECRET",
        "FOUNDRY_WORKER_CLIENT_SECRET",
    ):
        path = root / name
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o037 or not path.is_file() or path.is_symlink() or path.stat().st_size < 32:
            raise SystemExit("FAIL private nonempty regular secret file required: " + name)
    for name in (
        "TLS_DIRECTORY",
        "WAL_ARCHIVE_DIRECTORY",
        "KEYCLOAK_IMPORT_DIRECTORY",
        "INGESTION_DIRECTORY",
    ):
        if not Path(os.environ[name]).is_dir():
            raise SystemExit("FAIL missing operator directory: " + name)
    print(
        "PASS static production preflight; TLS, permissions, scans and recovery require "
        "separate checks"
    )


if __name__ == "__main__":
    main()
