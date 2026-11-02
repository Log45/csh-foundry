"""Explicit operator provisioning for a NEW cluster. Never invoked by API startup or CI."""

import argparse
import os
from pathlib import Path

import psycopg
from psycopg import sql


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--grant-runtime", action="store_true", help="Run after owner migrations")
    args = parser.parse_args()
    if not args.apply:
        print(
            "DRY RUN: create isolated foundry/keycloak databases and non-superuser "
            "owner/runtime roles"
        )
        print("After migrations: grant DML on application tables, no DDL or Alembic modification")
        return
    # This credential is operator-owned and must never reach application containers.
    with psycopg.connect(os.environ["FOUNDRY_ADMIN_DATABASE_URL"], autocommit=True) as connection:
        if args.grant_runtime:
            connection.execute("GRANT CONNECT ON DATABASE foundry TO foundry_runtime")
            # Connect directly to foundry for grants rather than assuming current database.
            from psycopg.conninfo import make_conninfo

            with psycopg.connect(
                make_conninfo(os.environ["FOUNDRY_ADMIN_DATABASE_URL"], dbname="foundry"),
                autocommit=True,
            ) as application:
                application.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
                application.execute("GRANT USAGE ON SCHEMA public TO foundry_runtime")
                application.execute(
                    "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO "
                    "foundry_runtime"
                )
                application.execute("REVOKE ALL ON alembic_version FROM foundry_runtime")
                application.execute("GRANT SELECT ON alembic_version TO foundry_runtime")
                application.execute(
                    "REVOKE UPDATE,DELETE,TRUNCATE ON authorization_audit FROM foundry_runtime"
                )
            print(
                "PASS runtime DML grants; runtime cannot own tables, migrate or rewrite "
                "security audit"
            )
            return
        for role, secret in (
            ("foundry_migrator", "migrator_password"),
            ("foundry_runtime", "runtime_password"),
            ("keycloak", "keycloak_password"),
        ):
            password = (args.secrets / secret).read_text().strip()
            if len(password) < 32:
                raise ValueError("Database passwords require at least 32 characters")
            connection.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOREPLICATION PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
        for database, owner in (("foundry", "foundry_migrator"), ("keycloak", "keycloak")):
            connection.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(database), sql.Identifier(owner)
                )
            )
            connection.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
            )
        print("PASS new database owners/runtime roles; run owner migrations then --grant-runtime")


if __name__ == "__main__":
    main()
