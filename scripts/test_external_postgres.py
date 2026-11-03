"""TLS and role checks against an explicitly supplied disposable test PostgreSQL URL."""

import os
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError


def main() -> None:
    url = os.environ["TEST_DATABASE_URL"]
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    if query.get("sslmode") != ["verify-full"]:
        raise SystemExit("NOT RUN: disposable verified-TLS database required")
    engine = create_engine(url, connect_args={"connect_timeout": 3})
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()"))
        assert connection.scalar(text("SHOW server_version_num")) >= "170000"
    engine.dispose()
    for name, candidate in (
        ("wrong-password", url.replace(parsed.password or "", "invalid-test-password", 1)),
        (
            "invalid-ca",
            urlunsplit(
                parsed._replace(
                    query=urlencode(
                        {k: v[0] for k, v in query.items()}
                        | {"sslrootcert": "/no-such-test-ca.pem"}
                    )
                )
            ),
        ),
        ("unavailable", urlunsplit(parsed._replace(netloc="u:p@127.0.0.1:1"))),
    ):
        probe = create_engine(candidate, connect_args={"connect_timeout": 2})
        try:
            with probe.connect():
                raise AssertionError("Connection unexpectedly succeeded: " + name)
        except OperationalError:
            print("PASS rejected " + name)
        finally:
            probe.dispose()
    print("PASS PostgreSQL verified TLS and bounded connection failures")


if __name__ == "__main__":
    main()
