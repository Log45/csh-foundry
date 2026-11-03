"""Bounded service/SQL diagnostics restricted to a disposable acceptance database."""

import argparse
import json
import re
import statistics
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ontology_platform.config import Settings
from ontology_platform.db.session import make_engine
from ontology_platform.queries.ast import QueryRequest
from ontology_platform.queries.service import QueryService
from ontology_platform.security.identity import resolve
from ontology_platform.security.service import PlatformAuthorizer
from pydantic import SecretStr
from sqlalchemy import URL, event
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"foundry-accept-[0-9a-f]{8}", args.project):
        raise ValueError("Disposable project required")
    private = ROOT / "artifacts" / args.project
    port = (
        subprocess.check_output(["docker", "port", args.project + "-postgres-1", "5432"], text=True)
        .strip()
        .rsplit(":", 1)[1]
    )
    url = URL.create(
        "postgresql+psycopg",
        username="foundry_migrator",
        password=(private / "secrets/migrator_password").read_text(),
        host="127.0.0.1",
        port=int(port),
        database="foundry",
    )
    settings = Settings(
        database_url=SecretStr(url.render_as_string(hide_password=False)), _env_file=None
    )
    engine, audit = make_engine(settings), make_engine(settings, audit=True)
    sessions = sessionmaker(engine)
    counts, timings, statements = [], [], []
    started = []

    @event.listens_for(engine, "before_cursor_execute")
    def before(conn, cursor, statement, parameters, context, many):
        started.append(time.perf_counter())
        if statement.startswith("SELECT objects."):
            statements.append((statement, parameters))

    @event.listens_for(engine, "after_cursor_execute")
    def after(conn, cursor, statement, parameters, context, many):
        timings.append(time.perf_counter() - started.pop())
        counts.append(statement.split()[0])

    try:
        from sqlalchemy import text

        with engine.connect() as sql:
            tenant = sql.scalar(
                text("SELECT tenant_id FROM objects WHERE object_type_id='Machine' LIMIT 1")
            )
        realm = json.loads((private / "realm/foundry-realm.json").read_text())
        subject = realm["users"][0]["id"]
        actor = resolve(
            sessions,
            "https://identity.accept.test/realms/foundry",
            subject,
            tenant,
            method="oidc",
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        service = QueryService(
            sessions, PlatformAuthorizer(sessions, audit_sessions=sessionmaker(audit))
        )
        measurements = []
        for traversal in (False, True):
            request = QueryRequest.model_validate(
                {
                    "object_type": "Machine",
                    **({"traverse": [{"link": "locatedInFactory"}]} if traversal else {}),
                }
            )
            for _index in range(20):
                counts.clear()
                timings.clear()
                stamp = time.perf_counter()
                result = service.query(actor, "manufacturing", request)
                measurements.append(
                    {
                        "operation": "traversal" if traversal else "query",
                        "service_ms": (time.perf_counter() - stamp) * 1000,
                        "ordinary_sql_ms": sum(timings) * 1000,
                        "ordinary_statements": len(counts),
                        "returned_objects": len(result.items),
                    }
                )
        plans = []
        # Keep only structural/timing/buffer data; never export SQL or parameters.
        allowed = {
            "Node Type",
            "Relation Name",
            "Index Name",
            "Actual Rows",
            "Actual Total Time",
            "Shared Hit Blocks",
            "Shared Read Blocks",
            "Execution Time",
            "Planning Time",
            "Plan",
            "Plans",
        }

        def redacted(value):
            if isinstance(value, dict):
                return {k: redacted(v) for k, v in value.items() if k in allowed}
            if isinstance(value, list):
                return [redacted(v) for v in value]
            return value

        seen = set()
        for statement, params in list(statements):
            if statement in seen:
                continue
            seen.add(statement)
            with engine.connect() as sql:
                plan = sql.exec_driver_sql(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, params
                ).scalar()
                plans.append(redacted(plan))
        checkout = []
        for _ in range(20):
            stamp = time.perf_counter()
            with engine.connect():
                checkout.append((time.perf_counter() - stamp) * 1000)
        args.output.write_text(
            json.dumps(
                {
                    "result": "PASS",
                    "measurements": measurements,
                    "plans": plans,
                    "idle_pool_checkout_median_ms": statistics.median(checkout),
                    "scope": "Disposable service/SQL diagnostic; excludes BFF/TLS, no claim "
                    "of explaining historical shared latency spike; security/audit remain enabled",
                },
                indent=2,
            )
            + "\n"
        )
    finally:
        engine.dispose()
        audit.dispose()


if __name__ == "__main__":
    main()
