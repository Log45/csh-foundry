"""Physical recovery helpers restricted to disposable Phase 10 acceptance projects."""

import json
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


def validate_source(info: dict[str, Any], project: str, archive: Path) -> None:
    if not re.fullmatch(r"foundry-accept-[0-9a-f]{8}", project):
        raise ValueError("Only disposable acceptance projects may run this drill")
    if (info["Config"].get("Labels") or {}).get("com.docker.compose.project") != project:
        raise ValueError("Source does not belong to this disposable project")
    expected = archive.resolve()
    if expected.name != "wal" or expected.parent.name != project:
        raise ValueError("Archive must be the disposable project's own WAL directory")
    mounts = [m for m in info["Mounts"] if m["Destination"] == "/archive"]
    # Docker Desktop rewrites Compose bind sources into its Linux VM's /host_mnt root.
    allowed = {expected, Path("/host_mnt" + str(expected))}
    if (
        len(mounts) != 1
        or mounts[0].get("Type") != "bind"
        or Path(mounts[0]["Source"]).resolve() not in allowed
    ):
        raise ValueError("Source archive mount differs from the disposable archive")


def docker(*args: str, input: str | None = None) -> str:
    return subprocess.check_output(
        ["docker", *args], input=input, text=True, stderr=subprocess.STDOUT
    ).strip()


def prepare_archive(source: str, project: str, archive: Path) -> dict[str, Any]:
    info = json.loads(docker("inspect", source))[0]
    validate_source(info, project, archive)
    docker("exec", source, "chown", "postgres:postgres", "/archive")
    docker("exec", "-u", "postgres", source, "test", "-w", "/archive")
    return info


def snapshot(container: str, database: str) -> dict[str, Any]:
    # psql formats identifiers from its own catalog, then executes bounded hash-only SELECTs.
    statement = r"""SELECT format(
      'SELECT json_build_object(%L, json_build_object(''rows'', count(*), ''hash'', '
      'md5(coalesce(string_agg(md5(to_jsonb(t)::text), '''' ORDER BY '
      'md5(to_jsonb(t)::text)),'''')))) FROM %I.%I t', tablename, schemaname, tablename)
      FROM pg_tables WHERE schemaname='public' ORDER BY tablename
\gexec
"""
    rows = docker(
        "exec",
        "-i",
        container,
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        "-d",
        database,
        "-At",
        input=statement,
    )
    result: dict[str, Any] = {}
    for row in rows.splitlines():
        result.update(json.loads(row))
    return result


def physical_recovery(
    *,
    source: str,
    project: str,
    archive: Path,
    private: Path,
    commit_record: Callable[[str], None],
) -> dict[str, Any]:
    info = prepare_archive(source, project, archive)
    image = info["Image"]  # Exact source image, not a mutable tag or a different PG build.
    volume: str | None = None
    restored: str | None = None
    target = project.replace("-", "_")
    started = time.monotonic()

    def sql(container: str, database: str, query: str) -> str:
        return docker(
            "exec",
            container,
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            database,
            "-Atc",
            query,
        )

    try:
        commit_record("before")
        base = "/tmp/" + target
        docker(
            "exec",
            "-u",
            "postgres",
            source,
            "pg_basebackup",
            "-U",
            "postgres",
            "-D",
            base,
            "-X",
            "stream",
            "-c",
            "fast",
        )
        commit_record("target")
        expected = {database: snapshot(source, database) for database in ("foundry", "keycloak")}
        target_lsn = sql(source, "foundry", f"SELECT pg_create_restore_point('{target}')")
        commit_record("after")
        archived_wal = sql(source, "foundry", "SELECT pg_walfile_name(pg_switch_wal())")
        assert re.fullmatch(r"[0-9A-F]{24}", archived_wal)
        for _ in range(120):
            probe = subprocess.run(
                ["docker", "exec", source, "test", "-f", "/archive/" + archived_wal],
                capture_output=True,
            )
            if probe.returncode == 0:
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("WAL archival failed for the complete-profile source")
        volume_name = project + "-pitr-restored"
        if (
            subprocess.run(
                ["docker", "volume", "inspect", volume_name], capture_output=True
            ).returncode
            == 0
        ):
            raise ValueError("Refusing to overwrite an existing recovery volume")
        volume = docker("volume", "create", volume_name)
        copy = subprocess.Popen(
            ["docker", "cp", source + ":" + base + "/.", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            extracted = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-i",
                    "--network",
                    "none",
                    "-v",
                    volume + ":/restore",
                    image,
                    "bash",
                    "-ec",
                    "tar -xf - -C /restore; touch /restore/recovery.signal; "
                    "chown -R postgres:postgres /restore; chmod 700 /restore",
                ],
                stdin=copy.stdout,
                capture_output=True,
            )
            assert copy.stdout is not None
            copy.stdout.close()
            copy.wait(timeout=30)
            assert copy.stderr is not None
            copy_error = copy.stderr.read()
            if copy.returncode or extracted.returncode:
                raise RuntimeError(
                    "Physical backup copy failed: " + (copy_error + extracted.stderr).decode()
                )
        finally:
            if copy.poll() is None:
                copy.kill()
                copy.wait()
        restored = docker(
            "run",
            "--rm",
            "-d",
            "--network",
            "none",
            "--name",
            project + "-pitr",
            "-v",
            volume + ":/var/lib/postgresql/data",
            "-v",
            str(archive.resolve()) + ":/archive:ro",
            image,
            "postgres",
            "-c",
            "restore_command=cp /archive/%f %p",
            "-c",
            "recovery_target_name=" + target,
            "-c",
            "recovery_target_action=promote",
            "-c",
            "archive_mode=off",
        )
        for _ in range(120):
            try:
                if sql(restored, "foundry", "SELECT NOT pg_is_in_recovery()") == "t":
                    break
            except subprocess.CalledProcessError:
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError("Restored cluster did not reach the target and promote")
        actual = {database: snapshot(restored, database) for database in expected}
        if expected != actual:
            raise AssertionError("Restored application/broker table hashes differ from target")
        records = sql(
            restored,
            "foundry",
            "SELECT string_agg(object_id,',' ORDER BY object_id) "
            "FROM objects WHERE object_type_id='Factory' AND object_id LIKE 'PITR-%'",
        )
        assert records == "PITR-before,PITR-target", records
        assert (
            sql(source, "foundry", "SELECT count(*) FROM objects WHERE object_id LIKE 'PITR-%'")
            == "3"
        )
        assert (
            sql(restored, "foundry", "SELECT version_num FROM alembic_version") == "0017_capacity"
        )
        stat = sql(
            source, "foundry", "SELECT archived_count||':'||failed_count FROM pg_stat_archiver"
        )
        return {
            "image_id": image,
            "server_version": sql(restored, "foundry", "SHOW server_version"),
            "target_name": target,
            "target_lsn": target_lsn,
            "archived_wal": archived_wal,
            "archiver_success_failure_counts": stat,
            "restored_records": records.split(","),
            "databases": expected,
            "seconds": round(time.monotonic() - started, 3),
            "scope": "Same-host disposable profile, actual governed records and full public-table "
            "checksums in foundry/keycloak; no target/off-host/RPO/RTO certification",
        }
    finally:
        if restored:
            (private / "pitr-postgres.log").write_text(docker("logs", restored))
            subprocess.run(["docker", "stop", restored], capture_output=True, check=False)
        if volume:
            subprocess.run(["docker", "volume", "rm", volume], capture_output=True, check=False)
