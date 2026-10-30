# Canonical SDK generator (Phase 9)

One implementation in `services/api/src/ontology_platform/sdk/` serves API and CLI generation.
Inputs are immutable published canonical definitions plus actual OpenAPI; outputs are independent
Python/TypeScript packages with deterministic source manifests/ZIPs. The canonical registry remains
authoritative. See [architecture and usage](../../docs/api/branching-sdk.md), ADR 0031 and the Phase 9 report.
