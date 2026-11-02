"""Start the restored local Keycloak/TLS containers before the existing Studio stack.

This does not restore, delete or reset a database, realm, user or credential.
See docs/development/keycloak-local.md for the one-time backup recovery procedure.
"""

import argparse
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISSUER = "https://keycloak.localhost/realms/foundry"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Rebuild API/Studio before starting")
    args = parser.parse_args()
    for name in ("foundry-keycloak", "foundry-keycloak-tls"):
        result = subprocess.run(["docker", "inspect", name], capture_output=True)
        if result.returncode:
            raise SystemExit("Missing " + name + "; follow the local Keycloak recovery runbook")
    subprocess.run(["docker", "start", "foundry-keycloak", "foundry-keycloak-tls"], check=True)
    ca = ROOT / "artifacts/keycloak-local/ca.pem"
    for _ in range(60):
        response = subprocess.run(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--max-time",
                "3",
                "--noproxy",
                "*",
                "--cacert",
                str(ca),
                "--resolve",
                "keycloak.localhost:443:127.0.0.1",
                ISSUER + "/.well-known/openid-configuration",
            ],
            capture_output=True,
            text=True,
        )
        if response.returncode == 0:
            try:
                if json.loads(response.stdout).get("issuer") == ISSUER:
                    break
            except ValueError:
                pass
        time.sleep(1)
    else:
        raise SystemExit("Keycloak HTTPS discovery is unavailable; API/Studio were not started")
    command = [
        "docker",
        "compose",
        "--env-file",
        str(ROOT / ".env"),
        "-f",
        str(ROOT / "infrastructure/compose.yaml"),
        "--profile",
        "studio",
        "up",
        "-d",
    ]
    if args.build:
        command.append("--build")
    subprocess.run(command + ["api", "studio"], cwd=ROOT, check=True)
    print("Studio: http://127.0.0.1:3000; Keycloak: https://keycloak.localhost/admin/")


if __name__ == "__main__":
    main()
