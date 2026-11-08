"""Test migrations/runtime as one unprivileged owner in a disposable local PostgreSQL cluster.

Requires installed initdb/pg_ctl and the repository Python dependencies.
The test-only cluster bootstrap creates one application owner, used for both migrations and
runtime. No existing database/role, production credential or external service is changed.
"""

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
from sqlalchemy import URL

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", default="", help="Optional pytest -k expression")
    args = parser.parse_args()
    initdb, pg_ctl = shutil.which("initdb"), shutil.which("pg_ctl")
    if not initdb or not pg_ctl:
        raise SystemExit("NOT RUN: installed PostgreSQL initdb and pg_ctl are required")
    with tempfile.TemporaryDirectory(prefix="foundry-owner-", dir="/tmp") as temporary:
        directory = Path(temporary)
        data, socket = directory / "data", directory / "socket"
        socket.mkdir(mode=0o700)
        subprocess.run(
            [
                initdb,
                "-D",
                str(data),
                "-U",
                "postgres",
                "-A",
                "trust",
                "--no-locale",
                "-E",
                "UTF8",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        started = False
        try:
            subprocess.run(
                [
                    pg_ctl,
                    "-D",
                    str(data),
                    "-l",
                    str(directory / "postgres.log"),
                    "-o",
                    f"-k {socket} -c listen_addresses='' -c timezone=UTC",
                    "-w",
                    "start",
                ],
                check=True,
            )
            started = True
            # PostgreSQL requires its bootstrap role to remain superuser. Use it only to
            # initialize this private test cluster's single application account; all migrations
            # and API/worker connections below use that same unprivileged database owner.
            with psycopg.connect(
                dbname="postgres", user="postgres", host=str(socket), autocommit=True
            ) as connection:
                connection.execute(
                    "CREATE ROLE foundry_owner LOGIN NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOREPLICATION"
                )
                connection.execute("ALTER DATABASE postgres OWNER TO foundry_owner")
            with psycopg.connect(
                dbname="postgres", user="foundry_owner", host=str(socket)
            ) as connection:
                flags = connection.execute(
                    "SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication "
                    "FROM pg_roles WHERE rolname=current_user"
                ).fetchone()
                assert flags == (False, False, False, False)
            url = URL.create(
                "postgresql+psycopg",
                username="foundry_owner",
                password=secrets.token_urlsafe(32),
                host="localhost",  # Libpq query host below selects the private Unix socket.
                database="postgres",
                query={"host": str(socket)},
            ).render_as_string(hide_password=False)
            env = os.environ | {
                "TEST_DATABASE_URL": url,
                # Domain fixtures use development bootstrap; startup tests construct explicit
                # production settings. Never reuse a caller's remote storage/TLS configuration.
                "FOUNDRY_ENVIRONMENT": "development",
                "FOUNDRY_DATABASE_TLS_REQUIRED": "false",
                "FOUNDRY_ARTIFACT_BACKEND": "disabled",
                "FOUNDRY_OWNER_RUNTIME_TEST": "true",
                "OPEN_ONTOLOGIES_BIN": str(ROOT / ".external/open-ontologies"),
            }
            print(
                "PASS one application migration/runtime owner; elevated role flags all false",
                flush=True,
            )
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    *[
                        "services/api/tests/" + name
                        for name in (
                            "test_owner_runtime_override.py",
                            "test_owner_runtime_postgres.py",
                            "test_job_execution.py",
                            "test_security_workflows.py",
                            "test_security_platform.py",
                            "test_ingestion_recovery.py",
                            "test_semantic.py",
                            "test_semantic_platform.py",
                            "test_fixtures.py",
                            "test_kubernetes.py",
                            "test_production_profile.py",
                        )
                    ],
                    *(["-k", args.selection] if args.selection else []),
                    "-ra",
                    "--tb=short",
                ],
                cwd=ROOT,
                env=env,
                check=True,
            )
        finally:
            if started:
                subprocess.run([pg_ctl, "-D", str(data), "-m", "fast", "-w", "stop"], check=True)


if __name__ == "__main__":
    main()
