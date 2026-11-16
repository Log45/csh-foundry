"""Run one durable ingestion job using the server's trusted local identity/catalog."""

import argparse
from uuid import UUID

from sqlalchemy.orm import sessionmaker

from ontology_platform.config import get_settings
from ontology_platform.db.session import make_engine
from ontology_platform.ingestion.catalog import SourceCatalog
from ontology_platform.ingestion.worker import IngestionWorker
from ontology_platform.security.workers import WorkerPool


def main() -> None:
    parser = argparse.ArgumentParser(description="Process one bounded ingestion run")
    parser.add_argument("--ontology", help="Optional queue filter")
    parser.add_argument("--cleanup-days", type=int)
    args = parser.parse_args()
    settings = get_settings()
    engine = make_engine(settings)
    try:
        sessions = sessionmaker(engine)
        pool = WorkerPool(settings, sessions)
        worker = IngestionWorker(
            sessions,
            pool.authorizer,
            SourceCatalog.from_json(settings.ingestion_catalog_json),
        )
        result: int | UUID | None
        if args.cleanup_days is not None:
            if not 7 <= args.cleanup_days <= 3650:
                parser.error("Retention must be 7–3650 days")
            result = sum(
                pool.run(
                    "cleanup",
                    lambda actor, scope: worker.cleanup(actor, scope, args.cleanup_days),
                    args.ontology,
                    cleanup_days=args.cleanup_days,
                )
            )
        else:
            result = next(pool.run("ingestion", worker.run_one, args.ontology), None)
        print(str(result) if result else "No eligible ingestion run")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
