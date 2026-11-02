"""Physical base backup and named-point WAL recovery on disposable isolated PostgreSQL 17."""

import secrets
import subprocess
import time


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True, stderr=subprocess.STDOUT).strip()


def main() -> None:
    name = "foundry-recovery-" + secrets.token_hex(6)
    containers: list[str] = []
    volumes: list[str] = []
    image = "postgres:17.6-bookworm"
    try:
        for suffix in ("archive", "backup", "restored"):
            volumes.append(docker("volume", "create", name + "-" + suffix))
        source = docker(
            "run",
            "--rm",
            "-d",
            "--network",
            "none",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-v",
            volumes[0] + ":/archive",
            "-v",
            volumes[1] + ":/backup",
            image,
            "postgres",
            "-c",
            "wal_level=replica",
            "-c",
            "archive_mode=on",
            "-c",
            "archive_command=cp %p /archive/%f",
        )
        containers.append(source)

        def sql(statement):
            return docker("exec", source, "psql", "-U", "postgres", "-Atc", statement)

        for _ in range(120):
            try:
                sql("SELECT 1")
                break
            except subprocess.CalledProcessError:
                time.sleep(0.25)
        else:
            raise RuntimeError("Recovery source did not start")
        docker("exec", source, "chown", "postgres:postgres", "/archive", "/backup")
        sql(
            "CREATE TABLE recovery_probe(id integer PRIMARY KEY); INSERT INTO "
            "recovery_probe VALUES (1)"
        )
        docker(
            "exec",
            "-u",
            "postgres",
            source,
            "pg_basebackup",
            "-U",
            "postgres",
            "-D",
            "/backup/base",
            "-X",
            "stream",
            "-c",
            "fast",
        )
        sql("INSERT INTO recovery_probe VALUES (2)")
        sql("SELECT pg_create_restore_point('phase10_verified')")
        sql("INSERT INTO recovery_probe VALUES (3)")
        switched = sql("SELECT pg_walfile_name(pg_switch_wal())")
        for _ in range(120):
            try:
                docker("exec", source, "test", "-f", "/archive/" + switched)
                break
            except subprocess.CalledProcessError:
                time.sleep(0.25)
        else:
            raise RuntimeError("WAL archival did not complete")
        # Copy a disposable base backup; no application/development database is touched.
        docker(
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            volumes[1] + ":/backup:ro",
            "-v",
            volumes[2] + ":/restore",
            image,
            "bash",
            "-ec",
            "cp -a /backup/base/. /restore/; touch /restore/recovery.signal; "
            "chown -R postgres:postgres /restore; chmod 700 /restore",
        )
        restored = docker(
            "run",
            "--rm",
            "-d",
            "--network",
            "none",
            "-v",
            volumes[2] + ":/var/lib/postgresql/data",
            "-v",
            volumes[0] + ":/archive:ro",
            image,
            "postgres",
            "-c",
            "restore_command=cp /archive/%f %p",
            "-c",
            "recovery_target_name=phase10_verified",
            "-c",
            "recovery_target_action=promote",
        )
        containers.append(restored)
        for _ in range(120):
            try:
                result = docker(
                    "exec",
                    restored,
                    "psql",
                    "-U",
                    "postgres",
                    "-Atc",
                    "SELECT string_agg(id::text, ',' ORDER BY id) FROM recovery_probe",
                )
                promoted = docker(
                    "exec",
                    restored,
                    "psql",
                    "-U",
                    "postgres",
                    "-Atc",
                    "SELECT NOT pg_is_in_recovery()",
                )
                if promoted == "t":
                    assert result == "1,2", "WAL target did not exclude post-target data"
                    break
            except subprocess.CalledProcessError:
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError("WAL recovery did not promote")
        print(
            "PASS PostgreSQL 17.6 physical base backup, WAL archival, named-point "
            "recovery and promotion"
        )
        print(
            "PASS pre-backup and committed post-backup records recovered; post-target "
            "record excluded"
        )
        print(
            "Scope: isolated Docker volumes; off-host encrypted storage and disaster-site "
            "recovery NOT RUN"
        )
    finally:
        for container in reversed(containers):
            subprocess.run(["docker", "stop", container], check=False, capture_output=True)
        for volume in volumes:
            subprocess.run(["docker", "volume", "rm", volume], check=False, capture_output=True)


if __name__ == "__main__":
    main()
