"""Process one semantic job under the configured initiating local principal."""

import argparse
import os
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from ontology_platform.config import get_settings
from ontology_platform.db.session import make_engine
from ontology_platform.security.interfaces import Principal
from ontology_platform.security.local import LocalAuthorizer
from ontology_platform.semantic.engine import OpenOntologiesAdapter
from ontology_platform.semantic.worker import SemanticWorker


def main() -> None:
    parser = argparse.ArgumentParser(description="Process one bounded semantic job")
    parser.add_argument("--ontology", required=True)
    args = parser.parse_args()
    settings = get_settings()
    if (
        not settings.trusted_local_identity
        or settings.local_tenant_id is None
        or not settings.local_principal_id
    ):
        parser.error("Explicit trusted local identity required")
    p = Principal(tenant_id=settings.local_tenant_id, principal_id=settings.local_principal_id)
    engine = make_engine(settings)
    try:
        worker = SemanticWorker(
            sessionmaker(engine),
            LocalAuthorizer(settings),
            engine=OpenOntologiesAdapter(
                Path(os.environ.get("OPEN_ONTOLOGIES_BIN", ".external/open-ontologies"))
            ),
        )
        print(worker.run_one(p, args.ontology) or "No eligible semantic job")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
