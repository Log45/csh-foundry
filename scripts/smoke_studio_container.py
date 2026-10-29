"""Read-only production Studio image probe; no configured identity, credentials or writes."""

import subprocess
import time

import httpx

container = subprocess.check_output(
    ["docker", "run", "--rm", "-d", "-p", "127.0.0.1::3000", "csh-foundry-studio:phase8"],
    text=True,
).strip()
try:
    port = (
        subprocess.check_output(["docker", "port", container, "3000"], text=True)
        .strip()
        .rsplit(":", 1)[1]
    )
    base = "http://127.0.0.1:" + port
    for _ in range(80):
        try:
            response = httpx.get(base, timeout=3)
            if response.status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    else:
        raise RuntimeError("Studio image did not start")
    assert "Your ontology." in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "'unsafe-eval'" not in response.headers["content-security-policy"]
    assert httpx.get(base + "/auth/session").status_code == 401
    assert (
        httpx.post(base + "/bff", json={"path": "/api/v1/ontologies", "method": "GET"}).status_code
        == 401
    )
    assert httpx.post(base + "/auth/login", headers={"Origin": base}).status_code == 503
    uid = subprocess.check_output(["docker", "exec", container, "id", "-u"], text=True).strip()
    assert uid != "0"
    print(
        "PASS production Studio image: root renders; security headers; no unsafe-eval; "
        "unauthenticated requests denied; unconfigured login fails closed; non-root runtime"
    )
finally:
    subprocess.run(["docker", "stop", container], check=True, stdout=subprocess.DEVNULL)
