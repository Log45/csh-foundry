"""Sample only the named disposable acceptance project's aggregate resources."""

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"foundry-accept-[0-9a-f]{8}", args.project):
        raise ValueError("Only disposable acceptance projects may be sampled")
    private = ROOT / "artifacts" / args.project
    password = (private / "secrets/migrator_password").read_text()
    container = args.project + "-postgres-1"
    port = (
        subprocess.check_output(["docker", "port", container, "5432"], text=True)
        .strip()
        .rsplit(":", 1)[1]
    )
    samples = []
    while True:
        containers = subprocess.check_output(
            ["docker", "ps", "-q", "--filter", "label=com.docker.compose.project=" + args.project],
            text=True,
        ).split()
        if not containers:
            break
        raw = subprocess.check_output(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}", *containers], text=True
        )
        sample = {"utc_epoch": time.time(), "containers": [json.loads(v) for v in raw.splitlines()]}
        try:
            with psycopg.connect(
                host="127.0.0.1",
                port=port,
                dbname="foundry",
                user="foundry_migrator",
                password=password,
                connect_timeout=2,
            ) as sql:
                values = sql.execute(
                    "SELECT (SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname='foundry'), (SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname='foundry' AND wait_event_type='Lock'), "
                    "(SELECT wal_bytes FROM pg_stat_wal), pg_database_size('foundry'), "
                    "(SELECT coalesce(sum(bytes_used),0) FROM tenant_resource_usage)"
                ).fetchone()
                sample["database"] = dict(
                    zip(
                        (
                            "connections",
                            "lock_waiters",
                            "wal_bytes",
                            "database_bytes",
                            "logical_artifact_bytes",
                        ),
                        values,
                        strict=True,
                    )
                )
                jobs = sql.execute(
                    "SELECT status,count(*),max(extract(epoch FROM "
                    "clock_timestamp()-created_at)) FROM (SELECT status,created_at FROM "
                    "ingestion_runs UNION ALL SELECT status,created_at FROM semantic_jobs) j "
                    "GROUP BY status"
                ).fetchall()
                sample["jobs"] = jobs
        except psycopg.Error as error:
            sample["database_error_type"] = type(error).__name__
        samples.append(sample)
        args.output.write_text(
            json.dumps(
                {
                    "interval_seconds": 10,
                    "samples": samples,
                    "scope": "Sampling began during sustained load; partial coverage",
                },
                indent=2,
                default=str,
            )
            + "\n"
        )
        time.sleep(10)


if __name__ == "__main__":
    main()
