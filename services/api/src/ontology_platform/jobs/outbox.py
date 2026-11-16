"""Deliver one outbox event to an operator-configured fixed HTTPS destination."""

import argparse
import os

from sqlalchemy.orm import sessionmaker

from ontology_platform.config import get_settings
from ontology_platform.db.session import make_engine
from ontology_platform.jobs.webhooks import WebhookRunner
from ontology_platform.security.workers import WorkerPool


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ontology", help="Optional queue filter")
    args = parser.parse_args()
    settings = get_settings()
    engine = make_engine(settings)
    try:
        sessions = sessionmaker(engine)
        pool = WorkerPool(settings, sessions)
        runner = WebhookRunner(sessions, pool.authorizer)
        url = os.environ["FOUNDRY_OUTBOX_DESTINATION"]
        result = next(
            pool.run(
                "outbox", lambda actor, scope: runner.run_one(actor, scope, url), args.ontology
            ),
            None,
        )
        print(result or "No eligible event")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
