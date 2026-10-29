# Worker boundary

Phase 4 provides a bounded PostgreSQL ingestion runner inside the modular API package:

```bash
uv run python -m ontology_platform.ingestion --ontology manufacturing
```

The server-managed catalog and trusted initiating principal are required. The runner handles one
eligible job and exits; operators may invoke multiple processes, with database leases/fencing and
retained ontology locks preserving correctness. No separate microservice, broker or distributed
orchestrator is introduced. Production process supervision/scheduling remains operator-managed.
See [ingestion documentation](../../docs/api/ingestion.md).
