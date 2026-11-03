"""Render and validate application deployment contracts; this is not SCC admission."""

import argparse
import json
import re
import subprocess
from pathlib import Path

import yaml


def validate(resources: list[dict], *, production: bool = False) -> None:
    identities = [(r["kind"], r["metadata"]["name"]) for r in resources]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate resource identities")
    services = {r["metadata"]["name"]: r for r in resources if r["kind"] == "Service"}
    pods = []
    for r in resources:
        if r["kind"] not in {"Deployment", "Job"}:
            continue
        template = r["spec"]["template"]
        pod = template["spec"]
        pods.append(template)
        assert pod["automountServiceAccountToken"] is False
        assert pod["securityContext"]["runAsNonRoot"] is True
        assert pod["securityContext"].get("runAsUser", 1) != 0
        assert not any(pod.get(k) for k in ("hostNetwork", "hostPID", "hostIPC"))
        for c in pod.get("initContainers", []) + pod["containers"]:
            sc = c["securityContext"]
            assert sc["runAsNonRoot"] and not sc["allowPrivilegeEscalation"]
            assert sc["readOnlyRootFilesystem"] and sc.get("runAsUser", 1) != 0
            assert sc["capabilities"] == {"drop": ["ALL"]}
            assert sc["seccompProfile"] == {"type": "RuntimeDefault"}
            assert not sc.get("privileged", False)
            assert re.fullmatch(r".+@sha256:[a-f0-9]{64}", c["image"])
            assert all(p["containerPort"] >= 1024 for p in c.get("ports", []))
            assert c["resources"]["requests"] and c["resources"]["limits"]
            assert not any(v.get("hostPath") for v in pod["volumes"])
            for mount in c["volumeMounts"]:
                assert any(v["name"] == mount["name"] for v in pod["volumes"])
            assert not any(
                word in " ".join(c.get("command", []))
                for word in ("chown", "chmod", "apt-get", "pip install")
            )
        if r["kind"] == "Deployment":
            assert all(
                template["metadata"]["labels"].get(k) == v
                for k, v in r["spec"]["selector"]["matchLabels"].items()
            )
            for c in pod["containers"]:
                assert all(k in c for k in ("startupProbe", "readinessProbe", "livenessProbe"))
    for service in services.values():
        selected = [
            p
            for p in pods
            if all(
                p["metadata"]["labels"].get(k) == v for k, v in service["spec"]["selector"].items()
            )
        ]
        assert selected, "Service selector has no workload"
        for port in service["spec"]["ports"]:
            assert all(
                any(
                    cp["name"] == port["targetPort"]
                    for c in p["spec"]["containers"]
                    for cp in c.get("ports", [])
                )
                for p in selected
            )
    for r in resources:
        if r["kind"] == "Route":
            assert r["spec"]["to"]["name"] in services
            assert r["spec"]["tls"] == {
                "termination": "edge",
                "insecureEdgeTerminationPolicy": "Redirect",
            }
            assert r["spec"]["to"]["name"] == "studio", "Internal API must remain private"
    assert not any(
        r["kind"] in {"SecurityContextConstraints", "ClusterRoleBinding"} for r in resources
    )
    raw = json.dumps(resources)
    assert '"anyuid"' not in raw and '"privileged"' not in raw
    if production:
        assert not any(
            value in raw
            for value in ("example.test", "example.invalid", "192.0.2.", "REPLACE_", "0" * 64)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("overlay", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    rendered = subprocess.check_output(["kubectl", "kustomize", str(args.overlay)], text=True)
    resources = list(yaml.safe_load_all(rendered))
    validate(resources, production=args.production)
    if args.output:
        args.output.write_text(rendered)
    print(f"PASS rendered contract: {len(resources)} resources; SCC admission NOT RUN")


if __name__ == "__main__":
    main()
