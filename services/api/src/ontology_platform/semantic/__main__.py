"""Process one semantic job under the configured initiating local principal."""

import argparse
import os
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from ontology_platform.config import get_settings
from ontology_platform.db.session import make_engine
from ontology_platform.security.workers import worker_context
from ontology_platform.semantic.engine import OpenOntologiesAdapter
from ontology_platform.semantic.worker import SemanticWorker


def main() -> None:
    parser = argparse.ArgumentParser(description="Process one bounded semantic job")
    parser.add_argument("--ontology", required=True)
    args = parser.parse_args()
    settings = get_settings()
    engine = make_engine(settings)
    try:
        sessions = sessionmaker(engine)
        p, authorizer = worker_context(settings, sessions, "semantic", args.ontology)
        worker = SemanticWorker(
            sessions,
            authorizer,
            engine=OpenOntologiesAdapter(
                Path(os.environ.get("OPEN_ONTOLOGIES_BIN", ".external/open-ontologies"))
            ),
        )
        print(worker.run_one(p, args.ontology) or "No eligible semantic job")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
