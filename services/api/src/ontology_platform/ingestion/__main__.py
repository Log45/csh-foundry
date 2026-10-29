"""Run one durable ingestion job using the server's trusted local identity/catalog."""

import argparse

from sqlalchemy.orm import sessionmaker

from ontology_platform.config import get_settings
from ontology_platform.db.session import make_engine
from ontology_platform.ingestion.catalog import SourceCatalog
from ontology_platform.ingestion.worker import IngestionWorker
from ontology_platform.security.workers import worker_context


def main() -> None:
    parser = argparse.ArgumentParser(description="Process one bounded ingestion run")
    parser.add_argument("--ontology", required=True)
    parser.add_argument("--cleanup-days", type=int)
    args = parser.parse_args()
    settings = get_settings()
    engine = make_engine(settings)
    try:
        sessions = sessionmaker(engine)
        actor, authorizer = worker_context(settings, sessions, "ingestion", args.ontology)
        worker = IngestionWorker(
            sessions,
            authorizer,
            SourceCatalog.from_json(settings.ingestion_catalog_json),
        )
        key = (
            worker.cleanup(actor, args.ontology, args.cleanup_days)
            if args.cleanup_days is not None
            else worker.run_one(actor, args.ontology)
        )
        print(str(key) if key else "No eligible ingestion run")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
