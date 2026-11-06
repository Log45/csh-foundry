# Browser schema isolation inspection

Automatic approval review initially rejected browser launch because schema isolation was unclear.
Inspection established: apps/studio/tests/e2e_backend.py invokes database.__wrapped__(None), then
make_world(db); services/api/tests/test_phase1.py creates test_phase1_<random UUID>, constructs an
engine with that search_path, migrates that engine, and drops that owned schema on fixture closure.
The API explicitly replaces app.state.sessions with w.sessions. BrowserStore and all workers use
that same session factory. No migration is issued on the shared public schema. Test OIDC listens
on 127.0.0.1:8443 and does not invoke or configure protected Keycloak. The next escalation included
these exact source locations and was approved. Both early harness launches timed out readiness due
to the code readiness constant still requiring 0025 while the disposable schema was at 0026.
No broader authorization or shared-data mutation was sought to resolve this.
