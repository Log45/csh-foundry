"""Actual nginx TLS, host validation and private-path checks on a disposable loopback port."""

import ipaddress
import os
import ssl
import subprocess
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def main() -> None:
    container = None
    with tempfile.TemporaryDirectory(prefix="foundry-ingress-") as directory:
        root = Path(directory)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Isolated ingress test")])
        now = datetime.now(UTC)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(hours=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        (root / "fullchain.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (root / "key.pem").write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        (root / "key.pem").chmod(0o600)
        template = Path("infrastructure/production/nginx.conf.template").read_text()
        for variable, value in (
            ("STUDIO_HOST", "studio.example.org"),
            ("API_HOST", "api.example.org"),
            ("IDENTITY_HOST", "identity.example.org"),
        ):
            template = template.replace("${" + variable + "}", value)
        (root / "default.conf").write_text(template)
        try:
            container = subprocess.check_output(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-d",
                    "-p",
                    "127.0.0.1::443",
                    "-p",
                    "127.0.0.1::80",
                    "-v",
                    f"{root}:/etc/nginx/tls:ro",
                    "-v",
                    f"{root / 'default.conf'}:/etc/nginx/conf.d/default.conf:ro",
                    os.environ.get(
                        "FOUNDRY_INGRESS_TEST_IMAGE", "csh-foundry-ingress:phase10-closure"
                    ),
                ],
                text=True,
            ).strip()
            subprocess.run(["docker", "exec", container, "nginx", "-t"], check=True)
            binding = subprocess.check_output(
                ["docker", "port", container, "443"], text=True
            ).strip()
            base = "https://127.0.0.1:" + binding.rsplit(":", 1)[1]
            plain_binding = subprocess.check_output(
                ["docker", "port", container, "80"], text=True
            ).strip()
            marker = "disposable-callback-log-sentinel"
            redirect = httpx.get(
                "http://127.0.0.1:"
                + plain_binding.rsplit(":", 1)[1]
                + "/auth/callback?code="
                + marker,
                headers={"Host": "studio.example.org"},
                trust_env=False,
            )
            assert redirect.status_code == 308
            assert redirect.headers["location"].startswith("https://studio.example.org/")
            with httpx.Client(
                verify=ssl.create_default_context(cafile=str(root / "fullchain.pem")),
                trust_env=False,
                timeout=3,
            ) as client:
                for _ in range(40):
                    try:
                        response = client.get(
                            base + "/internal/metrics", headers={"Host": "api.example.org"}
                        )
                        break
                    except httpx.HTTPError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("Ingress did not start")
                assert response.status_code == 404
                assert response.headers["strict-transport-security"] == "max-age=31536000"
                assert (
                    client.get(
                        base + "/admin/", headers={"Host": "identity.example.org"}
                    ).status_code
                    == 404
                )
                assert (
                    client.get(
                        base + "/internal/browser-state/session/test",
                        headers={
                            "Host": "studio.example.org",
                            "X-Forwarded-Host": "attacker.example",
                        },
                    ).status_code
                    == 404
                )
                try:
                    client.get(base + "/?code=" + marker, headers={"Host": "attacker.example"})
                except httpx.RemoteProtocolError:
                    pass
                else:
                    raise AssertionError("Unknown Host was not rejected")
            try:
                httpx.get(base + "/", headers={"Host": "api.example.org"}, trust_env=False)
            except httpx.ConnectError:
                pass
            else:
                raise AssertionError("Untrusted certificate accepted")
            logs = subprocess.check_output(["docker", "logs", container], text=True)
            assert marker not in logs
            assert '"event":"ingress_status"' in logs
            print("PASS HTTP redirects and default-host logs omit callback/query values")
            print(
                "PASS actual nginx configuration, trusted TLS, HSTS, private path "
                "isolation, unknown Host rejection"
            )
            print(
                "Scope: ingress contract; production DNS/certificates and full deployed "
                "topology are separate gates"
            )
        finally:
            if container:
                subprocess.run(["docker", "stop", container], check=True, capture_output=True)


if __name__ == "__main__":
    main()
