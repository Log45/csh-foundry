"""Exercise actual images with unknown UIDs, unrelated GIDs, read-only roots and no capabilities."""

import argparse
import json
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

PYTHON = r"""
import os,pwd,tempfile,json,signal,subprocess,time,urllib.request
from pathlib import Path
assert os.getuid()!=0 and os.getgid()!=0 and 0 not in os.getgroups()
try: pwd.getpwuid(os.getuid())
except KeyError: pass
else: raise AssertionError('Test UID unexpectedly exists in passwd')
with tempfile.TemporaryDirectory() as directory:
 Path(directory,'native.txt').write_text('temporary')
for directory in ['/app','/etc','/usr/local/bin']:
 try: Path(directory,'foundry-unauthorized').write_text('denied')
 except OSError: pass
 else: raise AssertionError('Unauthorized write: '+directory)
if not os.environ.get('SEMANTIC_TEST'):
 import polars as pl
 assert pl.read_csv('fixtures/machines.csv').height==20
 from ontology_platform.config import Settings
 from pydantic import SecretStr
 from ontology_platform.main import create_app
 from ontology_schema.models import OntologyDefinition
 from ontology_platform.sdk.generator import generate
 schema=OntologyDefinition.model_validate_json(Path('ontologies/examples/manufacturing.json').read_text())
 settings=Settings(database_url=SecretStr('postgresql+psycopg://u:p@127.0.0.1:1/db'),_env_file=None)
 app=create_app(settings)
 for language in ['python','typescript']:
  assert generate(schema,language,app.openapi()).archive().startswith(b'PK')
if os.environ.get('SEMANTIC_TEST'):
 from ontology_platform.semantic.engine import OpenOntologiesAdapter
 engine=OpenOntologiesAdapter(Path('/usr/local/bin/open-ontologies'))
 engine.validate_shapes(Path('fixtures/manufacturing-shapes.ttl').read_bytes(),Path('fixtures/manufacturing-data.ttl').read_bytes())
 engine.reason(Path('fixtures/manufacturing.ttl').read_bytes(),Path('fixtures/manufacturing-data.ttl').read_bytes())
else:
 env=os.environ|{'FOUNDRY_DATABASE_URL':'postgresql+psycopg://u:p@127.0.0.1:1/db'}
 process=subprocess.Popen(['uvicorn','ontology_platform.main:create_app','--factory','--host','127.0.0.1'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:
  for _ in range(80):
   try:
    assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/live'))['status']=='ok';break
   except OSError: time.sleep(.1)
  else: raise AssertionError('API startup failed')
 finally:
  process.terminate(); assert process.wait(timeout=35) in (0, -signal.SIGTERM)
 from ontology_platform.jobs.supervisor import run_child
 import threading,sys
 stop=threading.Event();threading.Timer(.5,stop.set).start()
 assert run_child([sys.executable,'-c','import time; time.sleep(60)'],stop,deadline=10)==124
operations = (
 'semantic SHACL/reasoning, temporary writes and immutable path rejection'
 if os.environ.get('SEMANTIC_TEST') else
 'native Polars, SDK ZIPs, API HTTP/SIGTERM, supervisor interruption, '
 'temporary writes and immutable path rejection'
)
print(json.dumps({'uid':os.getuid(),'gid':os.getgid(),'groups':os.getgroups(),
 'operations':operations}))
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = []
    for uid, gid in ((1001230001, 1001230002), (1004560001, 1004560002)):
        flags = [
            "docker",
            "run",
            "--rm",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--user",
            f"{uid}:{gid}",
            "--tmpfs",
            "/tmp:rw,size=128m,mode=1777",
            "--network",
            "none",
        ]
        for role in ("api", "semantic"):
            command = flags + (
                ["-e", "SEMANTIC_TEST=1", "--platform", "linux/amd64"] if role == "semantic" else []
            )
            command += [f"csh-foundry-{role}:phase10-okd4", "python", "-c", PYTHON]
            name = "foundry-nonroot-" + uuid.uuid4().hex[:10]
            command[2:2] = ["--name", name, "--label", "foundry.test=okd4"]
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=180)
            except subprocess.TimeoutExpired:
                result = subprocess.CompletedProcess(
                    command, 124, "", "Timed out after 180 seconds"
                )
            finally:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True)

            records.append(
                {
                    "role": role,
                    "uid": uid,
                    "gid": gid,
                    "exit_code": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr[-4000:],
                }
            )
        for role, port, command in (
            ("studio", 3000, []),
            ("ingress", 8080, ["--entrypoint", "nginx"]),
        ):
            with tempfile.TemporaryDirectory(prefix="foundry-nonroot-") as directory:
                root = Path(directory)
                root.chmod(0o755)
                (root / "nginx.conf").write_text(
                    "pid /tmp/nginx.pid; error_log /dev/stderr; events {} http { "
                    "access_log /dev/stdout; client_body_temp_path /tmp/client; "
                    "proxy_temp_path /tmp/proxy; fastcgi_temp_path /tmp/fastcgi; "
                    "uwsgi_temp_path /tmp/uwsgi; scgi_temp_path /tmp/scgi; "
                    "server { listen 8080; location /health/live { return 200 'ok'; } } }"
                )
                extra = (
                    ["-v", f"{root}/nginx.conf:/input/nginx.conf:ro"] if role == "ingress" else []
                )
                image = f"csh-foundry-{role}:phase10-okd4"
                cid = subprocess.check_output(
                    [flag for flag in flags if flag != "--rm"]
                    + ["-d"]
                    + extra
                    + command
                    + [image]
                    + (
                        ["-c", "/input/nginx.conf", "-g", "daemon off;"]
                        if role == "ingress"
                        else []
                    ),
                    text=True,
                ).strip()
                try:
                    # Execute the image's own runtime to verify HTTP without exposing a host port.
                    probe = [
                        "node",
                        "-e",
                        "fetch('http://127.0.0.1:3000/health/live')"
                        ".then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))",
                    ]
                    if role == "ingress":
                        probe = ["wget", "-qO-", f"http://127.0.0.1:{port}/health/live"]
                    for _ in range(60):
                        checked = subprocess.run(
                            ["docker", "exec", cid] + probe, capture_output=True, text=True
                        )
                        if checked.returncode == 0:
                            break
                        time.sleep(0.25)
                    else:
                        logs = subprocess.run(
                            ["docker", "logs", cid], capture_output=True, text=True
                        )
                        raise RuntimeError(role + " never became healthy: " + logs.stderr[-2000:])
                    started = time.monotonic()
                    subprocess.run(
                        ["docker", "stop", "--time", "35", cid],
                        check=True,
                        stdout=subprocess.DEVNULL,
                    )
                    exit_code = int(
                        subprocess.check_output(
                            ["docker", "inspect", "-f", "{{.State.ExitCode}}", cid], text=True
                        )
                    )
                    records.append(
                        {
                            "role": role,
                            "uid": uid,
                            "gid": gid,
                            "exit_code": exit_code,
                            "http": "PASS",
                            "shutdown_seconds": round(time.monotonic() - started, 3),
                        }
                    )
                finally:
                    subprocess.run(["docker", "rm", "-f", cid], stdout=subprocess.DEVNULL)
    args.output.write_text(json.dumps(records, indent=2) + "\n")
    if any(r["exit_code"] not in ((0, 143) if r["role"] == "studio" else (0,)) for r in records):
        raise SystemExit("FAIL see non-root records")
    print(f"PASS {len(records)} image/UID runs; groups exclude root; read-only roots")


if __name__ == "__main__":
    main()
