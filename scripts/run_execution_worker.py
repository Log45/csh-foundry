"""Run the trusted execution controller against an explicitly configured migrated database."""

import signal
import time

from ontology_platform.artifacts.config import StorageSettings
from ontology_platform.artifacts.s3 import S3ArtifactStore
from ontology_platform.automations.service import AutomationService
from ontology_platform.config import get_settings
from ontology_platform.db.session import make_engine
from ontology_platform.execution.worker import ExecutionWorker
from ontology_platform.pipelines.service import PipelineService
from ontology_platform.security.workers import worker_context
from sqlalchemy.orm import sessionmaker


def main() -> None:
    settings, storage = get_settings(), StorageSettings()
    engine = make_engine(settings)
    sessions = sessionmaker(engine, expire_on_commit=False)
    actor, auth = worker_context(settings, sessions, "execution", "projects")
    worker = ExecutionWorker(
        PipelineService(
            sessions, auth, storage, S3ArtifactStore(storage) if storage.backend == "s3" else None
        ),
        actor,
    )
    running = True

    def stop(signum: int, frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        automations = AutomationService(
            sessions, worker.service.authorizer, storage, worker.service.store
        )
        while running:
            worker.actor, _ = worker_context(settings, sessions, "execution", "projects")
            automations.tick(worker.actor)
            if worker.run_one() is None:
                time.sleep(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
