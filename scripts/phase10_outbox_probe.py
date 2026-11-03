"""Real disposable receiver and process-loss window for at-least-once outbox delivery."""

import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from ontology_platform.db.models import OutboxEvent
from ontology_platform.jobs.webhooks import WebhookRunner
from sqlalchemy import select


def exercise(acceptance):
    a = acceptance
    a.login()
    prefix = "/ontologies/manufacturing"
    definition = a.api("GET", prefix + "/versions/1.0.0")["definition"]
    definition["version"] = "1.2.0"
    a.api("POST", prefix + "/versions", definition)

    def publish(_index):
        response = a.request(
            "studio.accept.test",
            "/bff",
            "POST",
            cookies=a.cookie,
            headers={"Origin": a.origin, "x-csrf-token": a.csrf},
            json={
                "method": "POST",
                "path": "/api/v1" + prefix + "/versions/1.2.0/publish",
                "expected_tenant": str(a.tenant),
                "body": {},
            },
        )
        assert response.status_code in (200, 409)
        if response.status_code == 409:
            assert response.json()["error"]["code"] == "version_immutable"
        return response.status_code

    with ThreadPoolExecutor(8) as pool:
        statuses = list(pool.map(publish, range(8)))
    assert statuses.count(200) == 1 and statuses.count(409) == 7
    assert a.api("GET", prefix)["active_version"] == "1.0.0"
    assert a.api("GET", prefix + "/versions/1.2.0")["status"] == "PUBLISHED"
    a.record(
        "concurrent-schema-publication-immutable-version-and-separate-activation",
        published=1,
        expected_conflicts_409=7,
        unexpected_errors=0,
    )
    deliveries = []
    effects = set()

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            key = self.headers["X-Ontology-Event-ID"]
            deliveries.append(key)
            effects.add(key)  # An actual consumer must deduplicate before its own side effect.
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    receiver = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=receiver.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{receiver.server_port}/"

    def transport(_destination, event_id, payload):
        return httpx.post(url, json=payload, headers={"X-Ontology-Event-ID": event_id}).status_code

    runner = WebhookRunner(a.sessions, a.auth)
    try:
        # Drain only this fresh fixture's outbox to the disposable consumer.
        for _ in range(100):
            if (
                runner.run_one(
                    a.actor, "manufacturing", "https://receiver.example/events", transport=transport
                )
                is None
            ):
                break
        deliveries.clear()
        effects.clear()
        prefix = "/ontologies/manufacturing"
        a.login()
        obj = a.api("GET", prefix + "/objects/Machine/MCH-005")
        a.api(
            "POST",
            prefix + "/actions/UpdateMachineStatus/execute",
            {
                "parameters": {
                    "machineId": "MCH-005",
                    "newStatus": "RUNNING",
                    "expectedRevision": obj["version"],
                },
                "idempotency_key": "closure4-outbox-crash",
            },
        )
        code = """import json,os,sys,httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ontology_platform.security.interfaces import Principal
from ontology_platform.security.service import PlatformAuthorizer
from ontology_platform.jobs.webhooks import WebhookRunner
x=json.load(sys.stdin)
e=create_engine(x['database'],hide_parameters=True)
s=sessionmaker(e)
def transport(url,event,payload):
 r=httpx.post(x['receiver'],json=payload,headers={'X-Ontology-Event-ID':event})
 assert r.status_code==204
 os._exit(77)
WebhookRunner(s,PlatformAuthorizer(s)).run_one(Principal.model_validate(x['actor']),
 'manufacturing','https://receiver.example/events',transport=transport)
"""
        child = subprocess.run(
            [sys.executable, "-c", code],
            input=json.dumps(
                {
                    "database": a.url,
                    "actor": a.actor.model_dump(mode="json"),
                    "receiver": url,
                }
            ),
            text=True,
            capture_output=True,
            timeout=30,
        )
        assert child.returncode == 77 and len(deliveries) == 1
        with a.sessions() as sql:
            row = sql.scalar(select(OutboxEvent).where(OutboxEvent.status == "CLAIMED"))
            assert row is not None
            key = row.id
            assert row.attempts == 1
        assert (
            runner.run_one(
                a.actor, "manufacturing", "https://receiver.example/events", transport=transport
            )
            is None
        )
        assert (
            runner.run_one(
                a.actor,
                "manufacturing",
                "https://receiver.example/events",
                transport=transport,
                now=datetime.now(UTC) + timedelta(seconds=61),
            )
            == key
        )
        assert deliveries == [str(key), str(key)] and effects == {str(key)}
        with a.sessions() as sql:
            row = sql.scalar(select(OutboxEvent).where(OutboxEvent.id == key))
            assert row.status == "DELIVERED" and row.attempts == 2
        assert a.api("GET", prefix + "/objects/Machine/MCH-005")["version"] == obj["version"] + 1
        a.record(
            "real-outbox-receiver-process-loss-after-effect-before-checkpoint",
            child_exit=77,
            deliveries=2,
            consumer_effects=1,
            attempts=2,
            duplicate_claim_before_lease_expiry="DENIED",
            retry_after_lease="DELIVERED",
            transport_scope="Loopback test transport; production SSRF/TLS policy unchanged",
        )
    finally:
        receiver.shutdown()
        receiver.server_close()
        thread.join(timeout=5)
    temporary_storage(a)


def temporary_storage(acceptance):
    """Fill only an owned 16-MiB tmpfs; never consume host/DB disk headroom."""
    a = acceptance
    code = """import errno,json,os,tempfile
from pathlib import Path
from ontology_platform.semantic.engine import OpenOntologiesAdapter
warm=os.environ.get('WARM')=='true'
if warm: tempfile.gettempdir()
pressure=Path('/tmp/pressure')
try:
 with pressure.open('wb') as f:
  for _ in range(17): f.write(b'x'*1048576)
except OSError as e:
 assert e.errno==errno.ENOSPC
adapter=OpenOntologiesAdapter(Path('/usr/local/bin/open-ontologies'))
try:
 adapter.validate_ontology(Path('/app/fixtures/manufacturing.ttl').read_bytes())
except OSError as e:
 assert os.statvfs('/tmp').f_bavail==0
 assert e.errno==(errno.ENOSPC if warm else errno.ENOENT)
 failure=type(e).__name__
else:
 raise AssertionError('Expected full-tmpfs failure')
pressure.unlink()
result=adapter.validate_ontology(Path('/app/fixtures/manufacturing.ttl').read_bytes())
assert result.engine_version=='2.1.0'
print(json.dumps({'result':'PASS','failure':failure,'warm_cache':warm,
 'recovery':'pinned engine validation succeeds',
 'physical_bytes_bounded':16777216,
 'scope':'Adapter filesystem boundary; no database/network attached'}))
"""
    for warm in (False, True):
        result = json.loads(
            a.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    a.project + "-tmpfs-probe",
                    "--platform",
                    "linux/amd64",
                    "--network",
                    "none",
                    "--read-only",
                    "--tmpfs",
                    "/tmp:size=16m,mode=1777",
                    "--memory",
                    "768m",
                    "--cpus",
                    "1",
                    "--pids-limit",
                    "64",
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges",
                    "-e",
                    "WARM=" + str(warm).lower(),
                    a.values["SEMANTIC_IMAGE"],
                    "python",
                    "-c",
                    code,
                ]
            )
        )
        a.record("bounded-semantic-temporary-storage-and-engine-recovery", **result)
