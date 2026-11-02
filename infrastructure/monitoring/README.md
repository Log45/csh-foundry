# Phase 10 monitoring scope

`alerts.yaml` contains three provisional API rules: scrape availability, 5xx ratio and p95 latency.
Metrics are private and require the application service credential; public ingress rejects them.
Run `uv run python scripts/test_alert_delivery.py` to check these rules with actual Prometheus and
Alertmanager and verify a disposable receiver sees API-unavailable firing and resolution.
The two-minute production rule is unchanged. Evidence and limitations are in
`docs/architecture/evidence/phase-10-closure/alerts.json`.

This test uses a synthetic local scrape target. It does not configure production scrapers, receivers,
retention, ownership, or host/PostgreSQL/WAL/backup/worker/queue/storage probes. Those integrations
remain mandatory operator acceptance gates. See `docs/operations/production.md` and the readiness
matrix. Do not claim production alert delivery from this local test.
